# -*- coding: utf-8 -*-
"""左下格：文章面板。

点左上任一节点 -> 这里把「该节点 + 它所有后代」渲染成一篇可读的文章：
主题是标题、视频有标题 + 正文、层级用字号与缩进表达。

为什么是「一节点一组控件」而不是一个大 QTextEdit：
    若整篇塞进一个富文本控件，保存时无法知道哪一段属于哪个节点
    （除非另定一套分隔标记）。一节点一组控件，归属天然明确，
    改标题同步导图也就是顺手的事。

「点标题或正文直接改」实现为**始终可编辑**的无边框控件 —— 点进去
就能打字，是"点击可编辑"的超集，且 focusOut 保存更可靠。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 按「相对当前显示根的层级」取字号
_TOPIC_SIZES = [21, 17, 15, 14]
_VIDEO_SIZES = [16, 14, 13, 13]
_INDENT_PX = 16

_EDIT_STYLE = """
QLineEdit {
    background: transparent;
    border: none;
    padding: 0px;
    color: #0f172a;
}
QLineEdit:focus {
    background: #eef4ff;
    border-radius: 3px;
}
"""

_BODY_STYLE = """
QTextEdit {
    background: transparent;
    border: none;
    padding: 0px;
    color: #1f2937;
}
QTextEdit:focus {
    background: #f7faff;
    border-radius: 3px;
}
"""


class _BodyEdit(QTextEdit):
    """无边框、自动撑高的正文编辑框；失焦时发 focus_out。"""

    focus_out = Signal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(_BODY_STYLE)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(28)
        self._fitting = False
        self.document().contentsChanged.connect(self._fit)
        self.setFixedHeight(28)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_out.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fitting:
            self._fit()

    def _fit(self):
        if self._fitting:
            return
        w = self.viewport().width()
        if w <= 0:
            return
        self._fitting = True
        try:
            doc = self.document()
            doc.setTextWidth(w)
            h = int(doc.size().height()) + 10
            h = max(28, h)
            if abs(self.height() - h) > 1:
                self.setFixedHeight(h)
        finally:
            self._fitting = False


class ContentPane(QWidget):
    title_edited = Signal(object)      # 被改名的节点

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentPane")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll)

        self._host = QWidget()
        self._host.setStyleSheet("background: #ffffff;")
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(22, 18, 22, 28)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self._host)

        self._current = None
        self.show_node(None)

    # ------------------------------------------------------------------ 对外
    def show_node(self, node):
        self._current = node
        self._clear()
        if node is None:
            hint = QLabel("点击左上导图里的节点，这里显示对应的文章。")
            hint.setStyleSheet("color:#94a3b8; font-size:14px;")
            self._layout.addWidget(hint)
            self._layout.addStretch(1)
            return
        self._add_node(node, 0)
        self._layout.addStretch(1)
        self.scroll.verticalScrollBar().setValue(0)

    # ------------------------------------------------------------------ 内部
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_node(self, node, level):
        lv = min(level, 3)

        # ---- 标题（无边框，看起来像小标题，实际可编辑）----
        title = QLineEdit(node.name)
        title.setStyleSheet(_EDIT_STYLE)
        title.setFrame(False)
        f = title.font()
        f.setPointSize(_TOPIC_SIZES[lv] if node.is_topic() else _VIDEO_SIZES[lv])
        f.setBold(node.is_topic())
        title.setFont(f)
        title.setToolTip("直接改标题，失焦保存（导图上同步变）")
        title.editingFinished.connect(
            lambda n=node, e=title: self._commit_title(n, e))
        self._layout.addWidget(self._wrap_indent(title, level))
        self._layout.addSpacing(2 if node.is_topic() else 4)

        # ---- 正文（只有视频节点有）----
        if node.is_video():
            body = _BodyEdit(node.body or "")
            body.setToolTip("直接改正文，失焦保存")
            body.focus_out.connect(
                lambda n=node, e=body: self._commit_body(n, e))
            self._layout.addWidget(self._wrap_indent(body, level))
            self._layout.addSpacing(10 if level <= 1 else 6)

        for child in node.children:
            self._add_node(child, level + 1)

    @staticmethod
    def _wrap_indent(widget, level):
        """用左边距表达层级（比嵌套容器简单且不会撑破宽度）。"""
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(level * _INDENT_PX, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(widget)
        return holder

    def _commit_title(self, node, editor):
        new = editor.text().strip()
        if not new:
            editor.setText(node.name)      # 不接受空标题
            return
        if new != node.name:
            node.name = new
            self.title_edited.emit(node)

    @staticmethod
    def _commit_body(node, editor):
        node.body = editor.toPlainText()
