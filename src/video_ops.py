# -*- coding: utf-8 -*-
"""ffmpeg 视频操作：裁剪 / 合并 / 流探测 / 编码器探测。

三条硬规矩（都有实测依据）：
  1. 所有 subprocess 走 proc.py —— CREATE_NO_WINDOW，不出黑框
  2. 所有进度从 `-progress pipe:1` 解析，不靠"猜时间"
  3. **不猜**：编码器能不能用先真跑一次；合并能不能 `-c copy` 先真探测参数

为什么裁剪一律重编码、不用 `-c copy`（实测）：
    `-c copy` 只能从关键帧切。实测关键帧间隔**不可控** —— 用户的手机视频
    1 秒一个（误差 ≤1s），我们自己 ffmpeg 生成的样片 8~10 秒一个（误差最大
    8 秒，等于切了个寂寞）。间隔不由我们决定，所以不能赌。
    重编码慢，但精度由解码器保证，和关键帧无关。

为什么合并默认 concat filter（实测推理）：
    输入是**混合来源**：手机 MP4、录制的 WebM(vp8/opus)、裁剪产物(h264/aac)。
    concat demuxer 要求编码参数完全一致，混了就失败或产出坏文件。
    所以先真探测，全一致且都是整段才走 `-c copy`；否则一律重编码。
"""

import json
import os
import re
import subprocess
import threading
import time

import media
import proc


class VideoOpError(RuntimeError):
    """ffmpeg 操作失败。**明确抛出，不静默降级**。"""


class Cancelled(RuntimeError):
    """任务被取消（用户点了取消 / 关窗）。不是错误，调用方单独处理。"""


# --------------------------------------------------------------------------
# 可执行文件
# --------------------------------------------------------------------------
def ffmpeg():
    p = media.find_ffmpeg()
    if not p:
        raise VideoOpError(
            "找不到 ffmpeg。请把 ffmpeg.exe 放到 <项目>/tools/ 或加入 PATH。")
    return p


def ffprobe():
    ff = media.find_ffmpeg()
    if not ff:
        return None
    # 只在**同目录**里找 —— 路径里本身就有 "ffmpeg" 这个目录名，
    # 字符串替换会把它也换掉（这个坑 media.py 里已经记过一次）
    p = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    if os.path.isfile(p):
        return p
    import shutil
    return shutil.which("ffprobe")


# --------------------------------------------------------------------------
# 编码器选择：真跑一次，不靠"列表里有"
# --------------------------------------------------------------------------
_ENCODER = None

#: 硬件编码器的参数（NVENC 用 p1~p7 预设 + cq）
_ENCODER_ARGS = {
    "h264_nvenc": ["-preset", "p4", "-rc", "vbr", "-cq", "23"],
    "libx264": ["-preset", "veryfast", "-crf", "20"],
}


def _try_encoder(name):
    """真编一帧测试图案。列表里有 ≠ 跑得起来（驱动/显卡都可能翻车）。"""
    try:
        r = proc.run(
            [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=s=128x72:r=5:d=1",
             "-c:v", name, "-f", "null", "-"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return False, "启动失败"
    if r.returncode == 0:
        return True, "ok"
    return False, (r.stderr or "").strip().replace("\n", " ")[:200]


def pick_encoder(log=None):
    """选视频编码器。优先 h264_nvenc，跑不起来退 libx264。结果缓存。

    **不静默降级**：降级原因写日志（调用方传 log 回调）。
    """
    global _ENCODER
    if _ENCODER:
        return _ENCODER
    ok, why = _try_encoder("h264_nvenc")
    if ok:
        _ENCODER = "h264_nvenc"
        if log:
            log("编码器: h264_nvenc（硬件）")
    else:
        _ENCODER = "libx264"
        if log:
            log("编码器: libx264（h264_nvenc 不可用：%s）" % why)
    return _ENCODER


def reset_encoder_cache():
    """测试用：强制下次重新探测。"""
    global _ENCODER
    _ENCODER = None


def _venc_args(enc):
    return ["-c:v", enc] + _ENCODER_ARGS.get(enc, ["-preset", "veryfast"])


# --------------------------------------------------------------------------
# 探测
# --------------------------------------------------------------------------
def probe(path):
    """读一个媒体文件的格式与首条视频/音频流。失败返回 None。"""
    p = ffprobe()
    if not p or not os.path.isfile(path):
        return None
    try:
        r = proc.run([p, "-v", "error", "-show_format", "-show_streams",
                      "-of", "json", path],
                     capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout)
    except Exception:
        return None

    fmt = d.get("format") or {}
    out = {"duration": None, "size": None, "format": fmt.get("format_name"),
           "video": None, "audio": None}
    for key in ("duration", "size"):
        try:
            out[key] = float(fmt[key]) if fmt.get(key) is not None else None
        except (TypeError, ValueError):
            out[key] = None
    for s in d.get("streams") or []:
        if s.get("codec_type") == "video" and out["video"] is None:
            out["video"] = {
                "codec": s.get("codec_name"),
                "width": int(s.get("width") or 0),
                "height": int(s.get("height") or 0),
                "pix_fmt": s.get("pix_fmt"),
                "fps": _parse_fps(s.get("avg_frame_rate")),
            }
        elif s.get("codec_type") == "audio" and out["audio"] is None:
            out["audio"] = {
                "codec": s.get("codec_name"),
                "sample_rate": int(s.get("sample_rate") or 0),
                "channels": int(s.get("channels") or 0),
            }
    # 时长读不出来（MediaRecorder 产的 WebM 就没有 Duration 元素）时，
    # 退到 "format 里没有" —— 调用方自己决定怎么办，这里不编一个假的
    return out


def _parse_fps(s):
    if not s or s == "0/0":
        return 0.0
    num, _, den = str(s).partition("/")
    try:
        n, d = float(num), float(den or 1)
        return round(n / d, 3) if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def duration_of(path):
    """时长（秒）。读不到返回 0.0。"""
    st = probe(path)
    return float(st["duration"]) if st and st.get("duration") else 0.0


def list_dshow_devices():
    """列出 DirectShow 视频/音频设备名（降级录制路径要用）。

    ffmpeg 把设备清单打到 stderr，退出码非 0 是**正常的**（dummy 输入打不开）。
    """
    if not media.find_ffmpeg():
        return {"video": [], "audio": []}
    try:
        # 【必须显式 utf-8】ffmpeg 的报错里会带设备/文件名的本地编码字节，
        # 本机默认 GBK 解码会直接抛 UnicodeDecodeError（实测踩到），
        # 然后被下面这个 except 吞成"设备为空"——静默失败，比报错更坏。
        r = proc.run([ffmpeg(), "-hide_banner", "-list_devices", "true",
                      "-f", "dshow", "-i", "dummy"],
                     capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=30)
    except Exception as e:                              # noqa: BLE001
        return {"video": [], "audio": [], "error": "%s: %s" % (type(e).__name__, e)}
    out = _parse_dshow((r.stderr or "") + (r.stdout or ""))
    out["error"] = None
    return out


#: ffmpeg 9.x 的 dshow 清单格式：`[in#0 @ 0x..] "设备名" (video|audio|none)`
#: 老教程里的 `DirectShow video devices` 标题行**这个版本已经不打了**（实测）。
_DSHOW_LINE = re.compile(r'"([^"]+)"\s*\((video|audio|none)\)')


def _parse_dshow(text):
    """把 ffmpeg 的 dshow 清单文本解析成 {video:[], audio:[]}。

    单独抽出来是为了能拿**真实输出样本**做单测，不必依赖本机有没有摄像头。
    """
    out = {"video": [], "audio": []}
    for line in (text or "").splitlines():
        if "Alternative name" in line:
            continue                      # 同一设备的 PnP 路径别名，不是新设备
        m = _DSHOW_LINE.search(line)
        if not m:
            continue
        name, kind = m.group(1), m.group(2)
        if kind in ("video", "audio") and name not in out[kind]:
            out[kind].append(name)
    return out


# --------------------------------------------------------------------------
# 跑 ffmpeg（带进度）
# --------------------------------------------------------------------------
def _drain(stream, sink):
    try:
        for line in stream:
            sink.append(line)
            if len(sink) > 400:
                del sink[0]
    except Exception:
        pass


def run_with_progress(cmd, total_sec=0.0, on_progress=None, should_stop=None,
                      timeout=3600):
    """跑 ffmpeg，解析 `-progress pipe:1`，可取消。

    `out_time_ms` 这个名字在 ffmpeg 里其实是**微秒**（历史遗留的命名错误），
    所以优先用 `out_time_us`；两个都按微秒处理。
    """
    err = []
    try:
        p = proc.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace", bufsize=1)
    except Exception as e:                              # noqa: BLE001
        raise VideoOpError("启动 ffmpeg 失败：%s: %s" % (type(e).__name__, e)) from e

    t = threading.Thread(target=_drain, args=(p.stderr, err), daemon=True)
    t.start()

    t0 = time.monotonic()
    cancelled = False
    try:
        for line in p.stdout:
            if should_stop and should_stop():
                cancelled = True
                p.kill()
                break
            if time.monotonic() - t0 > timeout:
                p.kill()
                raise VideoOpError("ffmpeg 超时（%d 秒）" % timeout)
            k, sep, v = line.strip().partition("=")
            if not sep:
                continue
            if k == "out_time_us" or (k == "out_time_ms" and total_sec):
                if on_progress and total_sec > 0:
                    try:
                        on_progress(min(1.0, (float(v) / 1e6) / total_sec))
                    except (TypeError, ValueError):
                        pass
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=10)
    finally:
        try:
            p.stdout.close()
        except Exception:
            pass

    if cancelled:
        raise Cancelled("已取消")
    if p.returncode != 0:
        tail = "".join(err[-8:]).strip()
        raise VideoOpError("ffmpeg 退出码 %s\n  %s" % (p.returncode, tail[:600]))
    return True


# --------------------------------------------------------------------------
# 裁剪
# --------------------------------------------------------------------------
def _even(n):
    n = int(n)
    return n if n % 2 == 0 else n + 1


def clip(src, dst, start, end, on_progress=None, should_stop=None,
         log=None, _retry=True):
    """把 src 的 [start, end) 裁出来写成 dst（MP4 / H.264 + AAC）。

    **一律重编码**：`-c copy` 只能从关键帧切，实测关键帧间隔 1~10 秒不可控，
    切出来的起点会偏，最坏偏差等于一整个 GOP。
    """
    if not os.path.isfile(src):
        raise VideoOpError("源文件不存在：%s" % src)
    a = max(0.0, float(start))
    b = float(end)
    if b - a < 0.05:
        raise VideoOpError("区间太短（%.2f 秒）" % (b - a))
    dur = b - a

    enc = pick_encoder(log)
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1",
           "-ss", "%.3f" % a, "-i", src, "-t", "%.3f" % dur]
    cmd += _venc_args(enc)
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", dst]
    try:
        run_with_progress(cmd, dur, on_progress, should_stop)
    except VideoOpError:
        if enc != "h264_nvenc" or not _retry:
            raise
        # 硬件编码器跑一半翻车（极少见但确实有）→ 明确降级重试一次
        if log:
            log("h264_nvenc 执行失败，改用 libx264 重试")
        global _ENCODER
        _ENCODER = "libx264"
        return clip(src, dst, start, end, on_progress, should_stop, log,
                    _retry=False)
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise VideoOpError("ffmpeg 报了成功但没写出文件：%s" % dst)
    return dst


# --------------------------------------------------------------------------
# 合并
# --------------------------------------------------------------------------
def _sig(st):
    """编码参数指纹。一致才能 concat demuxer。"""
    if not st or not st.get("video"):
        return None
    v = st["video"]
    a = st["audio"]
    return (v["codec"], v["width"], v["height"], v["pix_fmt"],
            a["codec"] if a else None,
            a["sample_rate"] if a else None,
            a["channels"] if a else None)


def plan_merge(segs):
    """决定用哪条路。**真探测**，不猜。

    segs: [{"path":..., "start":..., "end":...}]

    返回 {"mode": "copy"|"filter", "reason":..., "streams":[...],
          "canvas": (w,h) 或 None, "fps": float}
    """
    streams = [probe(s["path"]) for s in segs]
    missing = [segs[i]["path"] for i, st in enumerate(streams)
               if not st or not st.get("video")]
    if missing:
        raise VideoOpError("这些文件读不出视频流，无法合并：%s" % missing)

    # 有没有哪一段是**子区间**（裁剪过的）—— 有就绝不能 -c copy
    partial = False
    for s, st in zip(segs, streams):
        d = float(st.get("duration") or 0)
        a = float(s.get("start") or 0)
        b = float(s.get("end") or 0)
        if not d or a > 0.05 or b < d - 0.05:
            partial = True
            break

    sigs = [_sig(st) for st in streams]
    same = all(x == sigs[0] for x in sigs)

    w = max(st["video"]["width"] for st in streams)
    h = max(st["video"]["height"] for st in streams)
    fps = max([st["video"]["fps"] for st in streams] or [0])
    canvas = None
    for st in streams:
        v = st["video"]
        if v["width"] != w or v["height"] != h:
            canvas = (_even(w), _even(h))
            break
    if canvas is None and any(not st["audio"] for st in streams):
        # 有段落没声音 → 走 filter 路补静音轨，画布仍按统一尺寸
        canvas = (_even(w), _even(h))

    if same and not partial and canvas is None:
        return {"mode": "copy", "reason": "编码参数一致且都是整段",
                "streams": streams, "canvas": None, "fps": fps or 25.0}
    why = []
    if not same:
        why.append("编码参数不一致")
    if partial:
        why.append("含裁剪子区间")
    if canvas:
        why.append("分辨率不一致，统一为 %dx%d" % canvas)
    return {"mode": "filter", "reason": "、".join(why),
            "streams": streams, "canvas": canvas, "fps": fps or 25.0}


def merge(segs, dst, on_progress=None, should_stop=None, log=None):
    """按顺序合并 segs 到 dst。返回 plan（调用方可把 reason 报给用户）。"""
    if len(segs) < 2:
        raise VideoOpError("至少两段才能合并")
    plan = plan_merge(segs)
    if log:
        log("合并方式: %s（%s）" % (plan["mode"], plan["reason"]))

    total = sum(max(0.0, float(s.get("end") or 0) - float(s.get("start") or 0))
                for s in segs)
    if plan["mode"] == "copy":
        _merge_copy(segs, dst, total, on_progress, should_stop)
    else:
        _merge_filter(segs, dst, plan, total, on_progress, should_stop, log)

    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise VideoOpError("合并报了成功但没写出文件：%s" % dst)
    return plan


def _merge_copy(segs, dst, total, on_progress, should_stop):
    """无损：concat demuxer。只在探测到参数完全一致时才会走到这里。"""
    import tempfile
    d = os.path.dirname(dst)
    fd, lst = tempfile.mkstemp(dir=d, prefix=".vkbconcat-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for s in segs:
                p = os.path.abspath(s["path"]).replace("'", "'\\''")
                f.write("file '%s'\n" % p)
        cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-nostats",
               "-progress", "pipe:1",
               "-f", "concat", "-safe", "0", "-i", lst,
               "-c", "copy", "-movflags", "+faststart", dst]
        run_with_progress(cmd, total, on_progress, should_stop)
    finally:
        try:
            os.remove(lst)
        except OSError:
            pass


def _merge_filter(segs, dst, plan, total, on_progress, should_stop, log):
    """重编码：concat filter。能处理参数不一致 / 子区间 / 缺音轨。"""
    enc = pick_encoder(log)
    W, H = plan["canvas"] or (0, 0)
    fps = plan["fps"]

    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1"]
    chains = []
    pairs = []          # 每段的 (视频标签, 音频标签)
    # filter_complex 里的 [N:v]/[N:a] 中 N 是**输入文件序号**，不是流序号。
    # 每个 -i 只占一个序号（视频音频同属那一个输入），补的 anullsrc 也算一个。
    n_inputs = 0
    streams = plan["streams"]

    for i, (s, st) in enumerate(zip(segs, streams)):
        a = max(0.0, float(s.get("start") or 0))
        b = float(s.get("end") or 0)
        d = max(0.05, b - a)
        cmd += ["-ss", "%.3f" % a, "-t", "%.3f" % d, "-i", s["path"]]
        vi = n_inputs
        n_inputs += 1

        # 视频链：统一到同一画布 + 同一帧率 + 同一像素格式 + 时间归零
        vf = ["setpts=PTS-STARTPTS"]
        if W and H:
            vf.append("scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H))
            vf.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (W, H))
        if fps:
            vf.append("fps=%s" % fps)
        vf.append("format=yuv420p")
        vf.append("setsar=1")
        chains.append("[%d:v]%s[v%d]" % (vi, ",".join(vf), i))

        if st.get("audio"):
            chains.append("[%d:a]asetpts=PTS-STARTPTS,"
                          "aformat=sample_fmts=fltp:sample_rates=48000:"
                          "channel_layouts=stereo[a%d]" % (vi, i))
        else:
            # 没声音的段补静音轨，否则 concat 的 [i:a] 引用直接失败
            cmd += ["-f", "lavfi", "-t", "%.3f" % d,
                    "-i", "anullsrc=r=48000:cl=stereo"]
            chains.append("[%d:a]asetpts=PTS-STARTPTS[a%d]" % (n_inputs, i))
            n_inputs += 1
        pairs.append(("[v%d]" % i, "[a%d]" % i))

    n = len(segs)
    cat = "".join("%s%s" % (v, a) for v, a in pairs)
    chains.append("%sconcat=n=%d:v=1:a=1[vout][aout]" % (cat, n))

    cmd += ["-filter_complex", ";".join(chains),
            "-map", "[vout]", "-map", "[aout]"]
    cmd += _venc_args(enc)
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", dst]
    run_with_progress(cmd, total, on_progress, should_stop)


# --------------------------------------------------------------------------
# 录制产物：补时长
# --------------------------------------------------------------------------
def fix_webm_duration(src, dst):
    """把 MediaRecorder 产的 WebM 无损重封装一份，补上 Duration。

    实测：MediaRecorder 写出的 WebM 头里没有时长（实时流不可能预先知道），
    ffprobe 报 duration=None，裁剪页的时间轴就画不出来。
    `-c copy` 重封装不重编码、无损、毫秒级，ffmpeg 会按实际数据算出时长写进去。
    """
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-i", src, "-c", "copy", "-f", "webm", dst]
    r = proc.run(cmd, capture_output=True, text=True,
                 encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0 or not os.path.isfile(dst):
        raise VideoOpError("重封装失败：%s" % (r.stderr or "").strip()[:400])
    return dst
