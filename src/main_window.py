# -*- coding: utf-8 -*-
"""工作台主窗口：十字分割的四格 + 四个真窗格。

布局（M2 已验证，本轮原样沿用）：
    outer      (Horizontal) = [left_col , right_col]    2 : 1
    left_col   (Vertical)   = [tree     , content  ]    2 : 1
    right_col  (Vertical)   = [done     , pending  ]    2 : 1

Qt 没有原生十字分割控件。3 个 splitter 里，竖线由 outer 的 handle 单独
承担、天然贯穿全高；横线由两个纵向 splitter 分担，靠 splitterMoved
联动同步（blockSignals + _syncing 两道防线）。
实测（PySide6 6.11.1）：setSizes() 不会发 splitterMoved，所以递归不会
发生；但真实拖动一定会发，且这是未写进文档的实现细节，两道防线都留着。
另一个实测要点：setSizes() 只是建议值、会被可用空间夹取，所以同步时
取 source.sizes() 的实际值。

接线：四个 pane 互相不认识，全部在这里连。
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

import mock_data
from panes import ContentPane, DonePane, PendingPane, TreePane

RATIO_TOP = 2
RATIO_BOTTOM = 1
HANDLE_WIDTH = 6
MIN_PANE_PX = 60
DEFAULT_W = 1440
DEFAULT_H = 920


class WorkspaceWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("视频知识库 · 工作台")

        self._syncing = False
        self._ready = False
        self._last_dragged = None

        # ---------------- 假数据 ----------------
        self.tree_root = mock_data.build_tree()
        self.settings_values = dict(mock_data.DEFAULT_SETTINGS)

        # ---------------- 四个窗格 ----------------
        self.tree_pane = TreePane(
            root=self.tree_root,
            node_factory=lambda name, kind: mock_data.MockNode(name, kind))
        self.content_pane = ContentPane()
        self.done_pane = DonePane(items=mock_data.build_done_items(),
                                  tree_root=self.tree_root)
        self.pending_pane = PendingPane(
            items=mock_data.build_pending_items(),
            item_factory=lambda name: mock_data.MockItem(
                name, datetime.now().strftime("%Y-%m-%d %H:%M")),
            settings_defaults=mock_data.DEFAULT_SETTINGS)

        # ---------------- 十字骨架 ----------------
        self.left_col = QSplitter(Qt.Vertical)
        self.left_col.addWidget(self.tree_pane)
        self.left_col.addWidget(self.content_pane)

        self.right_col = QSplitter(Qt.Vertical)
        self.right_col.addWidget(self.done_pane)
        self.right_col.addWidget(self.pending_pane)

        self.outer = QSplitter(Qt.Horizontal)
        self.outer.addWidget(self.left_col)
        self.outer.addWidget(self.right_col)

        self._configure(self.left_col, vertical=True)
        self._configure(self.right_col, vertical=True)
        self._configure(self.outer, vertical=False)

        self.left_col.splitterMoved.connect(
            lambda pos, idx: self._on_splitter_moved(self.left_col))
        self.right_col.splitterMoved.connect(
            lambda pos, idx: self._on_splitter_moved(self.right_col))

        self.setCentralWidget(self.outer)
        self.resize(DEFAULT_W, DEFAULT_H)
        self.statusBar().showMessage("就绪 · 本轮为界面原型，使用的是假数据")

        # ---------------- 接线 ----------------
        self.tree_pane.node_selected.connect(self.content_pane.show_node)
        self.content_pane.title_edited.connect(self._on_title_edited)
        self.pending_pane.item_finished.connect(self._on_item_finished)
        self.pending_pane.settings_saved.connect(self._on_settings_saved)
        self.pending_pane.status_message.connect(self._show_status)

        # 初始：文章面板显示整棵树
        self.content_pane.show_node(self.tree_root)

    # ------------------------------------------------------------------ 接线回调
    def _on_title_edited(self, node):
        """文章面板改了标题 -> 导图上同步，右上「已添加到树」的判断也跟着重算。"""
        self.tree_pane.refresh_node(node)
        self.done_pane.refresh()

    def _on_item_finished(self, item):
        """右下处理完成 -> 进右上。"""
        self.done_pane.add_item(item)
        self._show_status(f"「{item.video_name}」处理完成，已移入右上")

    def _on_settings_saved(self, values):
        self.settings_values.update(values)

    def _show_status(self, msg):
        self.statusBar().showMessage(msg, 6000)

    # ------------------------------------------------------------------ 配置
    def _configure(self, sp, vertical):
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(HANDLE_WIDTH)
        sp.setStretchFactor(0, RATIO_TOP)
        sp.setStretchFactor(1, RATIO_BOTTOM)
        for i in range(sp.count()):
            w = sp.widget(i)
            if vertical:
                w.setMinimumHeight(MIN_PANE_PX)
            else:
                w.setMinimumWidth(MIN_PANE_PX)

    # ------------------------------------------------------------------ 同步
    def _other(self, source):
        return self.right_col if source is self.left_col else self.left_col

    def _on_splitter_moved(self, source):
        self._last_dragged = source
        self._sync(source)

    def _sync(self, source):
        if not self._ready or self._syncing:
            return
        target = self._other(source)
        self._syncing = True
        try:
            target.blockSignals(True)
            target.setSizes(source.sizes())
            target.blockSignals(False)
        finally:
            self._syncing = False

    # ------------------------------------------------------------------ 初始尺寸
    def showEvent(self, event):
        super().showEvent(event)
        if not self._ready:
            self._apply_initial_sizes()
            self._ready = True

    def _apply_initial_sizes(self):
        h = self.height() or DEFAULT_H
        top = int(h * RATIO_TOP / (RATIO_TOP + RATIO_BOTTOM))
        vsizes = [top, h - top]
        for sp in (self.left_col, self.right_col):
            sp.blockSignals(True)
            sp.setSizes(vsizes)
            sp.blockSignals(False)

        w = self.width() or DEFAULT_W
        left_w = int(w * RATIO_TOP / (RATIO_TOP + RATIO_BOTTOM))
        self.outer.blockSignals(True)
        self.outer.setSizes([left_w, w - left_w])
        self.outer.blockSignals(False)

        self._sync(self.left_col)

    # ------------------------------------------------------------------ 测试辅助
    def column_heights(self):
        return list(self.left_col.sizes()), list(self.right_col.sizes())

    def columns_aligned(self, tol=1):
        left, right = self.column_heights()
        if len(left) != len(right):
            return False
        return all(abs(a - b) <= tol for a, b in zip(left, right))
