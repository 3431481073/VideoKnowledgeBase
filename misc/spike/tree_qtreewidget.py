#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M0 预研 · 路线 A：QTreeWidget + 周边 hack

验证目标（五个动作）：
  1. 拖动节点到另一个节点上松手  -> 成为其子节点
  2. 滚轮                        -> 缩放（改字号）
  3. 空白处按住左键拖动          -> 平移（驱动滚动条）
  4. 双击节点                    -> 折叠 / 展开（Qt 自带）
  5. 双击空白                    -> 弹输入框新建节点

另外验证：右侧实时打印"同步回数据模型"的结果，用来回答
"QTreeWidget 不提供 move 信号，拖动后怎么同步回 TreeNode"。

运行：
  D:\\MyProject\\VideoKnowledgeBase\\venv\\Scripts\\python.exe _spike\\tree_qtreewidget.py
"""

import sys

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

HINT = """【路线 A · QTreeWidget】
1. 拖动节点到另一个节点上松手  -> 成为子节点
2. 滚轮                        -> 缩放
3. 空白处按住拖动              -> 平移
4. 双击节点                    -> 折叠 / 展开
5. 双击空白                    -> 新建节点
右侧实时显示"从控件反推出来的数据模型"
"""


# --------------------------------------------------------------------------
# 与 knowledge_tree.TreeNode 同构的最小数据模型
# --------------------------------------------------------------------------
class Node:
    def __init__(self, name, children=None):
        self.name = name
        self.children = children if children is not None else []


def sample_tree():
    return Node("个人空间", [
        Node("交易体系", [
            Node("断板反包"),
            Node("量价关系"),
            Node("仓位管理"),
        ]),
        Node("技术基础", [
            Node("K线形态"),
            Node("均线系统"),
        ]),
        Node("心法"),
    ])


def _is_ancestor(ancestor, item):
    """item 是否是 ancestor 的后代"""
    p = item.parent()
    while p is not None:
        if p is ancestor:
            return True
        p = p.parent()
    return False


# --------------------------------------------------------------------------
# 核心：QTreeWidget + hack
# --------------------------------------------------------------------------
class ZoomPanTree(QTreeWidget):
    BASE_PT = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- 拖动改结构的基础设置 ---
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setExpandsOnDoubleClick(True)          # 动作 4 靠 Qt 自带
        self.setStyleSheet("QTreeWidget::branch { image: none; }")

        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPoint()
        self._pan_scroll = (0, 0)

        self.model_root = None
        self.on_model_changed = None

    # ---------------- 动作 2：滚轮缩放 ----------------
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._set_zoom(self._zoom * (1.1 if delta > 0 else 1 / 1.1))
        event.accept()

    def _set_zoom(self, z):
        self._zoom = max(0.4, min(3.0, z))
        f = QFont("Microsoft YaHei")
        f.setPointSizeF(self.BASE_PT * self._zoom)
        root = self.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            it = stack.pop()
            it.setFont(0, f)
            stack.extend(it.child(i) for i in range(it.childCount()))

    # ---------------- 动作 3：空白拖动平移 ----------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._pan_scroll = (self.horizontalScrollBar().value(),
                                self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            d = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(self._pan_scroll[0] - d.x())
            self.verticalScrollBar().setValue(self._pan_scroll[1] - d.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.LeftButton:
            self._panning = False
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------------- 动作 5：空白双击新建 ----------------
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self._new_node()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)        # 动作 4：节点双击交给 Qt

    def _new_node(self):
        name, ok = QInputDialog.getText(self, "新建节点", "节点名称：")
        if not ok or not name.strip():
            return
        parent = self.currentItem()
        if parent is None:
            it = QTreeWidgetItem(self)
        else:
            it = QTreeWidgetItem(parent)
            parent.setExpanded(True)
        it.setText(0, name.strip())
        self._set_zoom(self._zoom)
        self.setCurrentItem(it)
        self._sync_model_from_widget()

    # ---------------- 动作 1：drop ON item = 成为子节点 ----------------
    def dragMoveEvent(self, event):
        # 放宽判定，具体合法性在 dropEvent 里自己算
        event.acceptProposedAction()

    def dropEvent(self, event):
        items = self.selectedItems()
        target = self.itemAt(event.position().toPoint())

        if not items or target is None or target in items:
            event.ignore()
            return
        for it in items:
            if _is_ancestor(it, target):      # 禁止拖进自己的后代
                event.ignore()
                return

        for it in items:
            old_parent = it.parent() or self.invisibleRootItem()
            old_parent.removeChild(it)
            target.addChild(it)
        target.setExpanded(True)
        self.setCurrentItem(items[0])
        self._set_zoom(self._zoom)
        self._sync_model_from_widget()
        event.acceptProposedAction()

    # ---------------- 关键问题：把控件结构反推回数据模型 ----------------
    def _sync_model_from_widget(self):
        def build(item):
            n = Node(item.text(0))
            for i in range(item.childCount()):
                n.children.append(build(item.child(i)))
            return n

        root = self.invisibleRootItem()
        self.model_root = Node("__root__", [build(root.child(i))
                                            for i in range(root.childCount())])

        lines = []
        for c in self.model_root.children:
            _dump(c, 0, lines)
        if self.on_model_changed:
            self.on_model_changed("\n".join(lines))


def _dump(n, depth, out):
    out.append("  " * depth + n.name)
    for c in n.children:
        _dump(c, depth + 1, out)


def build_widget_tree(tree, node, parent_item=None):
    if parent_item is None:
        item = QTreeWidgetItem(tree)
    else:
        item = QTreeWidgetItem(parent_item)
    item.setText(0, node.name)
    item.setExpanded(True)
    for c in node.children:
        build_widget_tree(tree, c, item)
    return item


# --------------------------------------------------------------------------
# 窗口：左=树（占 splitter 一格，演示"与四格独立滚动共存"），右=数据模型文本
# --------------------------------------------------------------------------
class Demo(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M0 路线 A · QTreeWidget + hack")
        self.resize(1100, 700)

        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.addWidget(QLabel(HINT))

        splitter = QSplitter(Qt.Horizontal)

        self.tree = ZoomPanTree()
        data = sample_tree()
        for c in data.children:
            build_widget_tree(self.tree, c)
        self.tree._set_zoom(1.0)
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        splitter.addWidget(self.tree)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setWindowTitle("同步回数据模型的结果")
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)
        self.setCentralWidget(central)

        self.tree.on_model_changed = self.viewer.setPlainText
        self.tree._sync_model_from_widget()


def main():
    app = QApplication(sys.argv)
    w = Demo()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
