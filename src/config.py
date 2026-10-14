# -*- coding: utf-8 -*-
"""配置地基。

`data/config.json` 是唯一配置源。本模块负责：
  - 默认值合并（缺键补默认，不因缺键崩溃）
  - 旧键迁移（`api_key` -> `clean_api_key`）
  - 原子写入（临时文件 + os.replace，避免写一半断电损坏配置）

注意：`save_config()` 是**合并写**，不是截断写。任何调用方都必须
先 `load_config()` 拿到全量再改，否则会清掉其它键。
"""

import json
import os
import tempfile

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# --------------------------------------------------------------------------
# 模型档位 -> 本地路径
# 只列本机实测存在 model.bin 的档位。没有的档位不写进来，
# 这样 get_model_info() 能明确报 unknown_model 而不是指向一个空路径。
# --------------------------------------------------------------------------
MODEL_PATHS = {
    "base": r"D:\models\faster-whisper-base",      # 实测 141.0 MB
    "medium": r"D:\models\faster-whisper-medium",  # 实测 1459.7 MB
}

# --------------------------------------------------------------------------
# 显存需求（MiB）
# 实测值 + 余量。实测基准：medium / cuda / int8_float16 = 1053 MiB。
# 余量用于容纳 transcribe 过程中的中间张量与上下文开销。
# --------------------------------------------------------------------------
VRAM_REQUIRED_MB = {
    "base": 800,
    "medium": 1200,
}

# --------------------------------------------------------------------------
# 默认清洗提示词
# 只输出整理后的正文，不输出标题（标题由新 UI 取视频文件名）。
# 占位符 {text} 由 ai_processor 用 str.replace 填入 —— 不用 str.format，
# 这样用户自定义提示词里出现 { } 也不会把格式化搞崩。
# --------------------------------------------------------------------------
DEFAULT_CLEAN_PROMPT = """你是一个专业的中文语音转写校对整理助手。用户会给你一段从视频中自动识别出的文字，文字带有时间戳（单位为秒）。请你把它整理成一篇通顺、干净的正文。

### 第一步：整体感知
通读全文，理解说话者的主旨、情感基调和逻辑脉络。不纠错，不提取主题，只建立对整段内容的总体印象。

### 第二步：逐句校对（重点：同音字错误）
- 原始文本来自语音转写，最常见的错误是同音字错误。
- 当出现两个意义不相关的字组合成奇怪词语时，要高度警惕，结合上下文大胆纠正。
- 例如“择福”可能是“蛰伏”，“鸡角鸡”可能是“鸡脚筋”。必须根据语境判断并修正。
- 同时修复断句、标点、截断问题。
- 必须忠实原意，不得添加或删除信息。

### 第三步：质量自检
- 检查正文是否忠实原意，没有添加或删除信息。
- 确认正文非空，且不含时间戳。

### 输出要求（务必严格遵守）
- 只输出整理后的正文本身。
- 不要输出标题。
- 不要输出任何解释、说明、前言、后记或“以下是整理后的文字”之类的话。
- 不要使用 JSON、代码块围栏或 Markdown 标记。

以下是带时间戳的原始文本（时间格式：秒）：
{text}"""

# --------------------------------------------------------------------------
# 默认值
# --------------------------------------------------------------------------
DEFAULTS = {
    "whisper_model": "medium",          # 固定 medium，M5 设置面板无此入口
    "clean_url": "https://api.deepseek.com/v1/chat/completions",
    "clean_model": "deepseek-chat",
    "clean_api_key": "",
    "clean_prompt": DEFAULT_CLEAN_PROMPT,
}


# --------------------------------------------------------------------------
# 内部：原子写入
# --------------------------------------------------------------------------
def _atomic_write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# 公开 API
# --------------------------------------------------------------------------
def load_config():
    """读配置并与默认值合并。文件缺失/损坏/缺键都返回可用的完整 dict。"""
    raw = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
            else:
                print(f"[config] {CONFIG_FILE} 不是 JSON 对象，忽略")
        except Exception as e:
            print(f"[config] 读取失败，改用默认值: {e}")

    # 旧键迁移：api_key -> clean_api_key（仅当新键为空时）
    if not raw.get("clean_api_key") and raw.get("api_key"):
        raw["clean_api_key"] = raw["api_key"]

    cfg = dict(DEFAULTS)
    for k in DEFAULTS:
        v = raw.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue          # 空串视为未设置，沿用默认值
        cfg[k] = v
    return cfg


def save_config(cfg):
    """合并写回。传入的 dict 会覆盖到 DEFAULTS 之上，未知键也一并保留。"""
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        out.update(cfg)
    _atomic_write(CONFIG_FILE, json.dumps(out, ensure_ascii=False, indent=2))


def get_model_path(model_size):
    return MODEL_PATHS.get(model_size)


def vram_required_mb(model_size):
    return VRAM_REQUIRED_MB.get(model_size)
