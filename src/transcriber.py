# -*- coding: utf-8 -*-
"""Whisper 转写（GPU）。

为什么顶部要注入 PATH：
  ctranslate2 用**普通 LoadLibrary** 加载 cublas，走的是标准搜索序
  （PATH / 程序目录 / 系统目录），**不认 `os.add_dll_directory()`**。
  实测：只调 os.add_dll_directory 指向 nvidia 包目录，仍然报
  `Library cublas64_12.dll is not found or cannot be loaded`；
  改成把那些目录塞进 PATH 就通了。
  所以这段必须在 `import faster_whisper` **之前**执行。

  另外实测：**不需要** nvidia-cudnn-cu12 —— ctranslate2 4.8.1 自带
  `cudnn64_9.dll`，缺的只有 cublas / cudart / nvrtc 一族。
"""

import os
import site
import subprocess
import sys

import proc

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _setup_cuda_dll_path():
    """把 pip 装的 nvidia-* 里的 DLL 目录注入 PATH。返回注入的目录列表。"""
    roots = list(site.getsitepackages())
    try:
        import sysconfig
        purelib = sysconfig.get_paths().get("purelib")
        if purelib:
            roots.append(purelib)
    except Exception:
        pass

    dirs = []
    for r in roots:
        for sub in ("cublas", "cuda_runtime", "cuda_nvrtc"):
            d = os.path.join(r, "nvidia", sub, "bin")
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
    if dirs:
        os.environ["PATH"] = ";".join(dirs) + os.pathsep + os.environ.get("PATH", "")
    else:
        print("[transcriber] 未找到 nvidia-* 包目录；若转写报 cublas 缺失，"
              "请执行 uv pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 "
              "nvidia-cuda-nvrtc-cu12")
    return dirs


CUDA_DLL_DIRS = _setup_cuda_dll_path()

from faster_whisper import WhisperModel   # noqa: E402  必须在 PATH 注入之后
from opencc import OpenCC                 # noqa: E402

import config as app_config               # noqa: E402

# --------------------------------------------------------------------------
# 运行参数
# --------------------------------------------------------------------------
DEVICE = "cuda"

# 实测（medium，10 秒音频）：
#   int8_float16 -> 显存 +1053 MiB，加载 10.8s，推理 9.2s
#   float16      -> 显存 +1981 MiB，加载  3.5s，推理 10.1s
# 选 int8_float16：显存只要 53%（给 M6 的自动并发留余量），推理还快 9%。
# 代价是加载慢 7.3s，但模型在进程内只加载一次，属一次性成本。
COMPUTE_TYPE = "int8_float16"

_model = None
_model_key = None
_cc = OpenCC("t2s")


# --------------------------------------------------------------------------
# 模型解析与探测
# --------------------------------------------------------------------------
def _resolve_model_size(model_size=None):
    if model_size:
        return model_size
    try:
        return app_config.load_config().get("whisper_model", "medium")
    except Exception as e:
        print(f"[transcriber] 读取配置失败，回退 medium: {e}")
        return "medium"


def _probe_free_vram_mb():
    """用 nvidia-smi 子进程探当前可用显存（MiB）。不可用则返回 None。"""
    try:
        out = proc.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5)
        return int(out.decode(errors="ignore").strip().splitlines()[0])
    except Exception:
        return None


def get_model_info(model_size=None):
    """该模型能否在**当前**显存下加载。M6 用它决定并发度。

    返回 dict：
      model / path / device / compute_type
      available      bool    现在能不能加载
      reason         str     ok | unknown_model | missing_files | vram_insufficient | vram_unknown
      vram_required_mb / vram_free_mb
      hint           str     给用户看的人话
    """
    size = _resolve_model_size(model_size)
    path = app_config.get_model_path(size)
    need = app_config.vram_required_mb(size)

    info = {
        "model": size,
        "path": path,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "vram_required_mb": need,
        "vram_free_mb": None,
        "available": False,
        "reason": "ok",
        "hint": "",
    }
    known = ", ".join(sorted(app_config.MODEL_PATHS))

    if path is None:
        info["reason"] = "unknown_model"
        info["hint"] = f"未知的模型档位 {size!r}。本机可选：{known}。"
        return info

    if not os.path.isfile(os.path.join(path, "model.bin")):
        info["reason"] = "missing_files"
        info["hint"] = (f"模型文件不存在：{path}。请先下载该模型，"
                        f"或把 whisper_model 改成 {known}。")
        return info

    free = _probe_free_vram_mb()
    info["vram_free_mb"] = free
    if free is None:
        info["available"] = True
        info["reason"] = "vram_unknown"
        info["hint"] = "nvidia-smi 不可用，无法判断显存，放行尝试加载。"
        return info

    if need is not None and free < need:
        info["reason"] = "vram_insufficient"
        info["hint"] = (f"当前可用显存 {free} MiB，不足以加载 {size}"
                        f"（需要约 {need} MiB）。请关闭占用显存的程序后重试。")
        return info

    info["available"] = True
    return info


def get_model(model_size=None):
    """取模型单例。配置或参数对应的档位/精度变了会自动重载。"""
    global _model, _model_key

    size = _resolve_model_size(model_size)
    key = (size, DEVICE, COMPUTE_TYPE)
    if _model is not None and _model_key == key:
        return _model

    info = get_model_info(size)
    if not info["available"]:
        raise RuntimeError(f"无法加载转写模型：{info['hint']}")

    _model = WhisperModel(info["path"], device=DEVICE, compute_type=COMPUTE_TYPE)
    _model_key = key
    return _model


def reset_model():
    """丢弃当前模型单例，下次 get_model() 重新加载。M6 回收显存用。"""
    global _model, _model_key
    _model = None
    _model_key = None


# --------------------------------------------------------------------------
# 转写
# --------------------------------------------------------------------------
def transcribe_video_iter(video_path, language="zh", on_progress=None,
                          should_stop=None):
    """**逐段产出**转写结果，供长任务显示进度。

    faster-whisper 的 model.transcribe() 返回的是生成器，边解码边 yield，
    所以「已产出片段的 end ÷ 音频总时长」就是一个真实（而非假装）的进度。

    on_progress(done_sec, total_sec) 每段回调一次；
    should_stop() 返回真则提前结束（用户取消）。

    首次调用会在 get_model() 里加载模型（medium/int8_float16 实测约 11 秒），
    调用方应在此之前把状态置成"正在加载模型"。
    """
    model = get_model()
    segments, info = model.transcribe(
        video_path,
        language=language,
        vad_filter=True,
        initial_prompt="以下是普通话的句子。",
        beam_size=5,
        temperature=0.0
    )
    total = float(getattr(info, "duration", 0) or 0)
    for segment in segments:
        if should_stop is not None and should_stop():
            return
        text_simplified = _cc.convert(segment.text)
        yield {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text_simplified,
        }
        if on_progress is not None and total > 0:
            on_progress(float(segment.end), total)


def transcribe_video(video_path, language="zh"):
    """转写视频，返回带时间戳的分段列表（秒，简体中文）。

    保留原签名 —— 老调用方不用改。需要进度就改用 transcribe_video_iter。
    """
    return list(transcribe_video_iter(video_path, language=language))
