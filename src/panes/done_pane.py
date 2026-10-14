# -*- coding: utf-8 -*-
"""右上格：已完成条目列表 + 三个筛选 tab。

「已添加到树」用**实时推导**：拿条目标题（= 视频文件名）去导图里找
有没有同名视频节点。下一轮条目真正加进树时不需要额外同步状态；
本轮「改标题 -> 导图节点名变」之后，归属判断也会自动跟着变。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

TAB_ALL, TAB_IN_TREE, TAB_NOT_IN_TREE = 0, 1, 2


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


class _ItemRow(QWidget):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)

        title = QLabel(item.title)
        title.setStyleSheet("font-size:13px; font-weight:600; color:#0f172a;")
        title.setWordWrap(True)
        lay.addWidget(title)

        meta = QLabel(item.created)
        meta.setStyleSheet("font-size:11px; color:#94a3b8;")
        lay.addWidget(meta)

        summary = QLabel(item.summary)
        summary.setStyleSheet("font-size:12px; color:#475569;")
        summary.setWordWrap(True)
        lay.addWidget(summary)


class DonePane(QWidget):
    def __init__(self, items=None, tree_root=None, parent=None):
        super().__init__(parent)
        self.setObjectName("DonePane")
        self.items = list(items or [])
        self.tree_root = tree_root

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.tabs = QTabBar(self)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("全部")
        self.tabs.addTab("已添加到树")
        self.tabs.addTab("未添加")
        self.tabs.setStyleSheet("""
            QTabBar::tab { padding: 6px 14px; font-size: 13px; color:#475569; }
            QTabBar::tab:selected { color:#0f172a; font-weight:600;
                                    border-bottom: 2px solid #2e8b57; }
        """)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        outer.addWidget(self.tabs)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e5e7eb;")
        outer.addWidget(line)

        self.list = QListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setStyleSheet("QListWidget::item { border-bottom:1px solid #f1f5f9; }")
        outer.addWidget(self.list, 1)

        self.refresh()

    # ------------------------------------------------------------------ 对外
    def set_tree_root(self, root):
        self.tree_root = root
        self.refresh()

    def add_item(self, item):
        self.items.insert(0, item)
        self.refresh()

    def is_in_tree(self, item):
        """条目是否已添加到导图：按视频文件名找同名视频节点。"""
        if self.tree_root is None:
            return False
        for n in _walk(self.tree_root):
            if n.is_video() and n.name == item.video_name:
                return True
        return False

    def visible_items(self):
        idx = self.tabs.currentIndex()
        if idx == TAB_IN_TREE:
            return [i for i in self.items if self.is_in_tree(i)]
        if idx == TAB_NOT_IN_TREE:
            return [i for i in self.items if not self.is_in_tree(i)]
        return list(self.items)

    # ------------------------------------------------------------------ 渲染
    def refresh(self):
        self.list.clear()
        for item in self.visible_items():
            row = _ItemRow(item)
            li = QListWidgetItem()
            li.setSizeHint(QSize(0, row.sizeHint().height()))
            li.setData(Qt.UserRole, item)
            self.list.addItem(li)
            self.list.setItemWidget(li, row)
