# -*- coding: utf-8 -*-
"""界面模型：节点与条目。

**这不是"假数据类"** —— 它们是界面自己的数据模型，假数据链路和真实链路
共用同一套。放在这里是为了让 mock_data 和 store 都能引用，而 mock_data
反过来成了"造这套模型假实例的工厂"。

保持这两个类零依赖：任何一层都能 import，不会拉进 faster-whisper / requests。
"""

import os

_VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".wmv")


def _stem(name):
    """去掉扩展名。只认已知的视频后缀，别把「十大发」这种名字里的点吃掉。"""
    low = (name or "").lower()
    for ext in _VIDEO_EXTS:
        if low.endswith(ext):
            return name[: -len(ext)]
    stem, dot, _ext = (name or "").rpartition(".")
    return stem if (dot and stem) else (name or "")


class UINode:
    """知识树节点。kind = "topic"（主题/文字）或 "video"（内容）。

    item_id：内容节点指向来源条目（UIItem.iid）。「已添加/未添加」按这个判定，
    不按名字 —— 名字会因去后缀、改名而变，id 不会。

    nid：**持久 id**，会写进 knowledge_tree.json。刷新一次不能变，
    否则"已添加/未添加"和选中状态全会断。
    """

    def __init__(self, name, kind="topic", body="", children=None, item_id=None):
        self.name = name
        self.kind = kind
        self.body = body
        self.item_id = item_id
        self.children = []
        self.parent = None
        self.collapsed = False
        self.nid = None
        #: 隐形根（多根改造）。**只有树最外层那个容器是 True**，它不出现在界面上；
        #: 它的 children 才是用户看到的顶层节点 —— 顶层可以有好几个（"多根"）。
        self.virtual = False
        for c in children or []:
            self.add(c)

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def is_topic(self):
        return self.kind == "topic"

    def is_video(self):
        return self.kind == "video"

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class UIItem:
    """一条视频条目。假数据与真实数据共用。

    【两个名字必须分开】这是被真实数据教育出来的：
      video_name  显示名，用户随时可改（右下条目双击改名、树上改标题）
      media_name  磁盘上的真实文件名，**永不随改名变化**

    为什么：`base`（产物文件的命名锚点 raw/<base>.txt 等）与 `media`（播放 URL）
    都必须锚在真实文件名上。早先两者都从显示名算 —— 用户把
    「VID20260731063231」改名成「怪物和人类的十大发」之后，产物全部找不到，
    条目从「已完成」掉回「未处理」，重启后连播放都坏（URL 指向不存在的文件）。
    """

    def __init__(self, video_name, created, text="", media="", src="",
                 media_name=None):
        self.video_name = video_name
        self.created = created
        self.text = text
        #: 真实文件名。没显式给就从 media 的 basename 推，再退回显示名。
        self.media_name = media_name or (
            os.path.basename(media) if media else video_name)
        #: 播放用相对 URL。真实链路下 == "media/" + media_name
        self.media = media or ("media/" + self.media_name)
        self.clips = []                    # 裁剪/合并结果 [{media, start, end}]
        #: 这条条目是哪来的：原片 / 裁剪产物 / 合并产物
        self.origin = "source"
        #: 「覆盖原视频」待执行标记。本轮只记录，不动文件。
        self.overwrite = False
        #: 【出队】用户在**预处理队列**（处理视频浮层的那个列表）里把它拿掉了。
        #:
        #: 🔴 只影响"这条还显不显示在队列里"，**别的什么都不动**：
        #:    记录还在、导图节点还在、转写/清洗产物还在、视频文件还在。
        #:    所以它是**可逆的**（把这个位清掉，它就回队列）。
        #: 为什么要有这个位：那个列表是**预处理队列**（收件箱），不是条目库 ——
        #: 用户在那儿点 ✕ 的意思是"我暂时不处理它了"，**不是**"从我的知识库里删掉它"。
        #: （第一版把它接到了 delete_item 上，结果删队列里一条 → 导图上对应的
        #:   节点跟着没了。用户的损失就出在这儿。）
        self.dequeued = False
        #: 运行态（假处理与真处理共用字段名）
        self.stage = "idle"        # idle | queued | loading | transcribing | cleaning | done | error
        self.transcribe_pct = 0
        self.clean_pct = 0
        self.queued_pos = 0        # 排队位次（1 起；0 = 没排队）
        #: 进行中的一句话说明（「裁剪 42%」/「合并 3/7 段」）。运行态，不落盘
        self.note = ""
        self.error = None
        #: 非致命但要让人看见的事（如清洗被长度上限截断）
        self.warning = None
        #: 真实链路
        self.src = src
        self.transcribed = False
        self.ai_processed = False
        self.iid = None

    @property
    def title(self):
        """标题 = 视频文件名（规格定）。"""
        return self.video_name

    @property
    def title_stem(self):
        """去掉扩展名的**显示名** —— 视频名进导图时用这个。"""
        return _stem(self.video_name)

    @property
    def base(self):
        """产物文件的基名。**锚在真实文件名上**，改名不影响。"""
        return _stem(self.media_name)

    @property
    def summary(self):
        """摘要 = 正文截前 20 字（规格定）。"""
        s = "".join((self.text or "").split())
        return s[:20] + ("…" if len(s) > 20 else "")
