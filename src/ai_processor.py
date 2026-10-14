# -*- coding: utf-8 -*-
"""LLM 清洗。

URL / Model / API Key / 提示词全部可配置：显式参数优先，未传则从 config 取。
默认提示词只输出**正文**，不输出标题。

`parse_ai_response` 原样保留 —— 它只在 `expect_json=True` 时被调用。
默认路径不吃它：新提示词返回的是纯文本，而 parse_ai_response 的
“取第一个 { 到最后一个 }”兜底会把正文里的大括号当成 JSON 起点，抽出垃圾。
"""

import json
import re

import requests

import config as app_config

TIMEOUT_SEC = 120

# TODO(M7): 超过这个长度会被静默腰斩（长音频只清洗了前一段），需改为分片处理。
MAX_INPUT_CHARS = 6000
# TODO(M7): max_tokens 4000 在长文本下可能截断输出，需与分片方案一起重估。
MAX_OUTPUT_TOKENS = 4000


def parse_ai_response(content: str) -> dict:
    """
    从 AI 返回的文本中提取 JSON 对象。
    支持纯 JSON、带 ```json 代码块、带前后说明文字的情况。
    """
    if not content:
        return {"error": "解析失败", "raw": ""}

    content = content.lstrip('﻿')
    content = content.replace('​', '').replace('‌', '').replace('‍', '')

    # 优先提取 ```json ... ``` 代码块
    if content.startswith("```json"):
        end_marker = content.find("```", 7)
        if end_marker != -1:
            content = content[7:end_marker].strip()
        else:
            content = content[7:].strip()
    elif content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1:]
        if content.rstrip().endswith("```"):
            content = content.rstrip()[:-3]
        content = content.strip()

    # 尝试直接解析
    try:
        return json.loads(content, strict=False)
    except json.JSONDecodeError:
        pass

    # 提取第一个 { 到最后一个 }
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = content[start:end + 1]
        try:
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError:
            # 漏逗号修复
            keys_to_fix = ["\"title\"", "\"cleaned_text\""]
            for key in keys_to_fix:
                pattern = r'([}\]])(\s*)' + re.escape(key)
                json_str = re.sub(pattern, lambda m: f"{m.group(1)},{m.group(2)}{key}", json_str)
            try:
                return json.loads(json_str, strict=False)
            except json.JSONDecodeError:
                pass

    return {"error": "解析失败", "raw": content}


def build_timestamped_text(segments):
    """把分段拼成带时间戳的原文 —— 清洗的输入。抽出来是为了让调用方
    能**事先**判断会不会被 MAX_INPUT_CHARS 截断，并把这件事告诉用户。"""
    lines = []
    for seg in segments:
        lines.append(f"[{seg['start']:.1f} - {seg['end']:.1f}] {seg['text']}")
    return "\n".join(lines)


def will_truncate(segments):
    """本次清洗会不会因为长度上限而被截断（TODO(M7) 未修，但要让用户看见）。"""
    return len(build_timestamped_text(segments)) > MAX_INPUT_CHARS


def process_segments(segments, api_key=None, url=None, model=None,
                     prompt=None, expect_json=False):
    """
    输入带时间戳分段，输出清洗后的正文。

    参数为 None 时从 config 取（url / model / prompt / api_key）。
    返回 {"title": str, "cleaned_text": str}。
    """
    cfg = None

    def _cfg():
        nonlocal cfg
        if cfg is None:
            cfg = app_config.load_config()
        return cfg

    if url is None:
        url = _cfg()["clean_url"]
    if model is None:
        model = _cfg()["clean_model"]
    if prompt is None:
        prompt = _cfg()["clean_prompt"]
    if not api_key:
        api_key = _cfg()["clean_api_key"]
    if not api_key:
        raise ValueError("缺少清洗 API Key（config.clean_api_key 为空）")

    timestamped_text = build_timestamped_text(segments)

    if len(timestamped_text) > MAX_INPUT_CHARS:
        timestamped_text = timestamped_text[:MAX_INPUT_CHARS] + "……（内容过长，已截断）"

    # 用 replace 而不是 str.format —— 允许用户自定义提示词里含 { }
    if "{text}" in prompt:
        user_content = prompt.replace("{text}", timestamped_text)
    else:
        user_content = prompt + "\n\n" + timestamped_text

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的文本校对和知识整理助手。"},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": MAX_OUTPUT_TOKENS
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_SEC)
    response.raise_for_status()
    result = response.json()
    content = result["choices"][0]["message"]["content"]

    if expect_json:
        parsed = parse_ai_response(content)
        if "error" in parsed:
            raise ValueError(f"AI 返回格式错误: {parsed.get('raw', '')[:200]}")
        cleaned_text = (parsed.get("cleaned_text") or parsed.get("text") or "").strip()
        title = (parsed.get("title") or "").strip()
    else:
        # 新提示词只产出正文；parse_ai_response 在此路径上会误判，故不调用
        cleaned_text = (content or "").strip()
        # TODO(M2): 标题定为视频文件名，此键在新 UI 中不再使用
        title = ""

    return {
        "title": title,
        "cleaned_text": cleaned_text
    }
