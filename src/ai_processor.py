import requests
import json
import os
import re

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-chat"


# ========== 场景一：自动 AI 整理（单一标题 + 清洁全文） ==========
PROMPT_TEMPLATE = """你是一个专业的中文语音转写校对整理助手。用户提供了一段从视频中自动识别出的文字，文字带有时间戳（单位为秒）。你的任务是：

### 第一步：整体感知
通读全文，理解说话者的主旨、情感基调和逻辑脉络。不纠错，不提取主题，只建立对整段内容的总体印象。

### 第二步：逐句校对（重点：同音字错误）
- 原始文本来自语音转写，最常见的错误是同音字错误。
- 当出现两个意义不相关的字组合成奇怪词语时，要高度警惕，结合上下文大胆纠正。
- 例如“择福”可能是“蛰伏”，“鸡角鸡”可能是“鸡脚筋”。必须根据语境判断并修正。
- 同时修复断句、标点、截断问题。
- 输出无时间戳的清洁文本，必须忠实原意，不得添加或删除信息。

### 第三步：生成总标题
- 基于清洁文本，提炼出该视频的**一个总主题标题**，概括整个视频的核心内容。
- **标题必须单一、具体、非叙事、非复合**。
- 禁止使用“与”“和”“及”等并列连词拼接两个概念。
- 禁止感叹式陈述。
- 禁止空标题。

### 第四步：质量自检
- 检查标题是否单一、精炼、非叙事、非复合。
- 检查清洁文本是否忠实原意，没有添加或删除信息。
- 确认标题和清洁文本都非空。
- 若发现问题，自行修正后再输出。

请严格按照以下 JSON 格式输出，不要包含任何其他文字、注释、代码块标记或 Markdown 格式：
{{
  "title": "视频总标题",
  "cleaned_text": "清洁后的完整原文，不含时间戳"
}}

以下是带时间戳的原始文本（时间格式：秒）：
{text}"""


def parse_ai_response(content: str) -> dict:
    """
    从 AI 返回的文本中提取 JSON 对象。
    支持纯 JSON、带 ```json 代码块、带前后说明文字的情况。
    """
    if not content:
        return {"error": "解析失败", "raw": ""}

    content = content.lstrip('\ufeff')
    content = content.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')

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


def process_segments(segments: list, api_key: str) -> dict:
    """
    输入带时间戳分段，输出视频总标题和清洁全文。
    返回格式：{"title": str, "cleaned_text": str}
    """
    if not api_key:
        raise ValueError("缺少 DeepSeek API Key")

    lines = []
    for seg in segments:
        lines.append(f"[{seg['start']:.1f} - {seg['end']:.1f}] {seg['text']}")
    timestamped_text = "\n".join(lines)

    if len(timestamped_text) > 6000:
        timestamped_text = timestamped_text[:6000] + "……（内容过长，已截断）"

    prompt = PROMPT_TEMPLATE.format(text=timestamped_text)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一个严谨的文本校对和知识整理助手。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }

    response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    result = response.json()
    content = result["choices"][0]["message"]["content"]
    parsed = parse_ai_response(content)
    if "error" in parsed:
        raise ValueError(f"AI 返回格式错误: {parsed.get('raw', '')[:200]}")

    return {
        "title": parsed.get("title", "").strip(),
        "cleaned_text": parsed.get("cleaned_text", "").strip()
    }