import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from faster_whisper import WhisperModel
from opencc import OpenCC

MODEL_PATH = r"D:\models\faster-whisper-medium"

_model = None
_cc = OpenCC('t2s')

def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_PATH, device="cpu", compute_type="int8")
    return _model

def transcribe_video(video_path, language="zh"):
    """转写视频，返回带时间戳的分段列表（秒，简体中文）"""
    model = get_model()
    segments, info = model.transcribe(
        video_path,
        language=language,
        vad_filter=True,
        initial_prompt="以下是普通话的句子。",
        beam_size=5,
        temperature=0.0
    )
    results = []
    for segment in segments:
        text_simplified = _cc.convert(segment.text)
        results.append({
            "start": segment.start,
            "end": segment.end,
            "text": text_simplified
        })
    return results