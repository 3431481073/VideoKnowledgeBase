import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TREE_FILE = os.path.join(BASE_DIR, "data", "knowledge_tree.json")


class TreeNode:
    def __init__(self, name, video=None, start=None, end=None, text=None, cleaned_file=None, topic_id=None, video_list=None):
        self.name = name
        self.children = []
        self.video = video                      # 主视频路径
        self.video_list = video_list or []      # 合并节点的多个视频路径
        self.start = start
        self.end = end
        self.text = text
        self.cleaned_file = cleaned_file
        self.topic_id = topic_id

    def is_content(self):
        return self.video is not None or bool(self.video_list)

    def is_topic(self):
        return not self.is_content()

    def to_dict(self):
        return {
            "name": self.name,
            "children": [child.to_dict() for child in self.children],
            "video": self.video,
            "video_list": self.video_list,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "cleaned_file": self.cleaned_file,
            "topic_id": self.topic_id
        }

    @staticmethod
    def from_dict(data):
        node = TreeNode(
            data["name"],
            video=data.get("video"),
            start=data.get("start"),
            end=data.get("end"),
            text=data.get("text"),
            cleaned_file=data.get("cleaned_file"),
            topic_id=data.get("topic_id"),
            video_list=data.get("video_list", [])
        )
        node.children = [TreeNode.from_dict(c) for c in data.get("children", [])]
        return node


def load_tree():
    if os.path.exists(TREE_FILE):
        with open(TREE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TreeNode.from_dict(data)
    else:
        root = TreeNode("个人空间")
        save_tree(root)
        return root


def save_tree(root):
    with open(TREE_FILE, "w", encoding="utf-8") as f:
        json.dump(root.to_dict(), f, ensure_ascii=False, indent=2)


def is_video_mounted(root, video_path):
    """检查视频是否已挂载到树中（支持合并节点的 video_list）"""
    for child in root.children:
        if child.is_content():
            if child.video == video_path or video_path in child.video_list:
                return True
        elif child.is_topic():
            if is_video_mounted(child, video_path):
                return True
    return False


def remove_video_from_tree(root, video_path):
    """从树中移除指定视频路径对应的内容节点，并清理空主题节点"""
    if root is None:
        return root

    for child in list(root.children):
        if child.is_content():
            if child.video == video_path or video_path in child.video_list:
                root.children.remove(child)
        elif child.is_topic():
            remove_video_from_tree(child, video_path)
            if not child.children:
                root.children.remove(child)

    return root