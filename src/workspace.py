import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
WORKSPACE_FILE = os.path.join(BASE_DIR, "data", "workspace.json")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw_transcripts")
AI_DIR = os.path.join(BASE_DIR, "data", "ai_processed")
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(AI_DIR, exist_ok=True)


def format_size(size_bytes):
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        gb = mb / 1024
        return f"{gb:.2f} GB"
    elif mb >= 1:
        return f"{mb:.1f} MB"
    else:
        kb = size_bytes / 1024
        return f"{kb:.0f} KB"


def format_time(seconds):
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"


class VideoItem:
    def __init__(self, file_path):
        self.file_path = file_path
        self.name = os.path.basename(file_path)
        self.size = os.path.getsize(file_path)      # 直接获取，不耗时
        self.created = os.path.getctime(file_path)  # 创建时间，直接获取
        self.transcribed = False
        self.ai_processed = False
        self.mounted = False
        self.refresh_status()

    def refresh_status(self):
        base_name = os.path.splitext(self.name)[0]
        raw_txt = os.path.join(RAW_DIR, base_name + ".txt")
        raw_json = os.path.join(RAW_DIR, base_name + "_segments.json")
        self.transcribed = os.path.exists(raw_txt) and os.path.exists(raw_json)

        ai_txt = os.path.join(AI_DIR, base_name + "_cleaned.txt")
        ai_json = os.path.join(AI_DIR, base_name + "_meta.json")
        self.ai_processed = os.path.exists(ai_txt) and os.path.exists(ai_json)

    def get_raw_text_path(self):
        base_name = os.path.splitext(self.name)[0]
        return os.path.join(RAW_DIR, base_name + ".txt")

    def get_segments_path(self):
        base_name = os.path.splitext(self.name)[0]
        return os.path.join(RAW_DIR, base_name + "_segments.json")

    def get_ai_text_path(self):
        base_name = os.path.splitext(self.name)[0]
        return os.path.join(AI_DIR, base_name + "_cleaned.txt")

    def get_meta_path(self):
        base_name = os.path.splitext(self.name)[0]
        return os.path.join(AI_DIR, base_name + "_meta.json")


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def load_workspace():
    items = []
    last_import_dir = ""
    if os.path.exists(WORKSPACE_FILE):
        try:
            with open(WORKSPACE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_import_dir = data.get("last_import_dir", "")
            for node_data in data.get("items", []):
                _extract_videos(node_data, items)
        except Exception as e:
            print(f"加载工作区失败: {e}")
    return items, last_import_dir


def save_workspace(items, last_import_dir=""):
    data = {"last_import_dir": last_import_dir, "items": []}
    for item in items:
        if isinstance(item, VideoItem):
            data["items"].append({"type": "video", "file_path": item.file_path})
    try:
        with open(WORKSPACE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存工作区失败: {e}")


def _extract_videos(node_data, items):
    """递归提取所有视频节点，兼容旧版合并组数据"""
    if not isinstance(node_data, dict):
        return
    node_type = node_data.get("type")
    if node_type == "video":
        file_path = node_data.get("file_path")
        if file_path and os.path.exists(file_path):
            items.append(VideoItem(file_path))
    elif node_type == "merge":
        for child_data in node_data.get("children", []):
            _extract_videos(child_data, items)