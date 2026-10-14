#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M0 预研 · 路线 B：QGraphicsView + QGraphicsScene 自绘

验证目标（五个动作）：
  1. 拖动节点到另一个节点上松手  -> 成为其子节点（重跑布局）
  2. 滚轮                        -> setTransform 缩放（AnchorUnderMouse）
  3. 空白处按住左键拖动          -> 平移（驱动滚动条）
  4. 双击节点                    -> 折叠 / 展开（重算布局）
  5. 双击空白                    -> 弹输入框新建节点（挂在当前选中节点下）

与路线 A 的关键差异：节点是自绘的，连线是三次贝塞尔曲线，布局自己算。

运行：
  D:\\MyProject\\VideoKnowledgeBase\\venv\\Scripts\\python.exe _spike\\tree_scene.py
"""

import sys

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------- 常量
NODE_H = 36.0
NODE_MIN_W = 84.0
PAD_X = 18.0
H_GAP = 26.0
V_GAP = 74.0

NODE_FONT = QFont("Microsoft YaHei", 10)
BADGE_FONT = QFont("Microsoft YaHei", 8)

C_TOPIC_BORDER = QColor("#2e8b57")
C_LEAF_BORDER = QColor("#94a3b8")
C_DROP_BORDER = QColor("#ef4444")
C_FILL = QColor("#f8fafc")
C_FILL_SEL = QColor("#dbeafe")
C_TEXT = QColor("#0f172a")
C_EDGE = QColor("#94a3b8")

HINT = """【路线 B · QGraphicsScene 自绘】
1. 拖动节点到另一个节点上松手  -> 成为子节点（红色高亮 = 落点）
2. 滚轮                        -> 缩放（鼠标位置为锚点）
3. 空白处按住拖动              -> 平移
4. 双击节点                    -> 折叠 / 展开
5. 双击空白                    -> 新建节点（挂在当前选中节点下）
"""


# ---------------------------------------------------------------- 数据模型
class MindNode:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.parent = None
        self.collapsed = False
        self.item = None
        # 布局结果
        self.subtree_w = 0.0
        self.x = 0.0
        self.y = 0.0
        self.w = NODE_MIN_W

    def is_topic(self):
        return bool(self.children)

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child


def sample_tree():
    root = MindNode("个人空间")
    t = root.add(MindNode("交易体系"))
    t.add(MindNode("断板反包"))
    t.add(MindNode("量价关系"))
    t.add(MindNode("仓位管理"))
    s = root.add(MindNode("技术基础"))
    s.add(MindNode("K线形态"))
    s.add(MindNode("均线系统"))
    root.add(MindNode("心法"))
    return root


def is_descendant_of(candidate, node):
    """candidate 是否是 node 的后代"""
    p = candidate.parent
    while p is not None:
        if p is node:
            return True
        p = p.parent
    return False


# ---------------------------------------------------------------- 节点图元
class NodeItem(QGraphicsItem):
    def __init__(self, node, canvas):
        super().__init__()
        self.node = node
        self.canvas = canvas
        self.w = NODE_MIN_W
        self.h = NODE_H
        self.is_drop_target = False
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        node.item = self

    # QGraphicsItem 接口
    def boundingRect(self):
        return QRectF(-self.w / 2.0, -self.h / 2.0, self.w, self.h)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)

        painter.setBrush(QBrush(C_FILL_SEL if self.isSelected() else C_FILL))
        if self.is_drop_target:
            painter.setPen(QPen(C_DROP_BORDER, 2.6))
        elif self.node.is_topic():
            painter.setPen(QPen(C_TOPIC_BORDER, 1.6))
        else:
            painter.setPen(QPen(C_LEAF_BORDER, 1.2))
        painter.drawPath(path)

        painter.setPen(QPen(C_TEXT))
        painter.setFont(NODE_FONT)
        painter.drawText(r, Qt.AlignCenter, self.node.name)

        if self.node.collapsed and self.node.children:
            painter.setPen(QPen(C_DROP_BORDER))
            painter.setFont(BADGE_FONT)
            painter.drawText(QRectF(self.w / 2.0 - 26, -self.h / 2.0, 26, self.h),
                             Qt.AlignCenter, f"+{len(self.node.children)}")

    # 交互
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self.canvas.selected_node = self.node
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.canvas.update_drop_target(self)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.canvas.finish_drag(self)

    def mouseDoubleClickEvent(self, event):
        self.canvas.toggle_collapse(self.node)
        event.accept()


# ---------------------------------------------------------------- 画布
class Canvas(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = None
        self.selected_node = None
        self._dragging = None

    # ---------- 布局 ----------
    def set_root(self, root):
        self.root = root
        self.rebuild()

    def rebuild(self):
        keep = self.selected_node
        self.clear()
        if self.root is None:
            return
        fm = QFontMetricsF(NODE_FONT)
        self._measure(self.root, fm)
        self._place(self.root, 0.0, 0)
        self.root.item = None
        self._create_items(self.root)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-600, -600, 600, 600))
        if keep is not None:
            self.selected_node = keep
            if keep.item is not None:
                keep.item.setSelected(True)

    def _measure(self, node, fm):
        own = max(NODE_MIN_W, fm.horizontalAdvance(node.name) + 2 * PAD_X)
        node.w = own
        if node.collapsed or not node.children:
            node.subtree_w = own
        else:
            total = sum(self._measure(c, fm) for c in node.children)
            total += H_GAP * (len(node.children) - 1)
            node.subtree_w = max(own, total)
        return node.subtree_w

    def _place(self, node, left, depth):
        node.x = left + node.subtree_w / 2.0
        node.y = depth * (NODE_H + V_GAP) + NODE_H / 2.0
        if node.collapsed or not node.children:
            return
        total = sum(c.subtree_w for c in node.children) + H_GAP * (len(node.children) - 1)
        cx = left + (node.subtree_w - total) / 2.0
        for c in node.children:
            self._place(c, cx, depth + 1)
            cx += c.subtree_w + H_GAP

    def _create_items(self, node):
        item = NodeItem(node, self)
        item.w = node.w
        item.setPos(node.x, node.y)
        self.addItem(item)
        if node.collapsed:
            return
        for c in node.children:
            self.addItem(self._make_edge(node, c))
            self._create_items(c)

    @staticmethod
    def _make_edge(parent, child):
        p1 = QPointF(parent.x, parent.y + NODE_H / 2.0)
        p2 = QPointF(child.x, child.y - NODE_H / 2.0)
        dy = p2.y() - p1.y()
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(QPointF(p1.x(), p1.y() + dy * 0.5),
                     QPointF(p2.x(), p2.y() - dy * 0.5),
                     p2)
        e = QGraphicsPathItem(path)
        e.setPen(QPen(C_EDGE, 1.6))
        e.setZValue(1)
        return e

    # ---------- 动作 4：折叠 / 展开 ----------
    def toggle_collapse(self, node):
        if not node.children:
            return
        node.collapsed = not node.collapsed
        self.selected_node = node
        self.rebuild()

    # ---------- 动作 1：拖动改结构 ----------
    def update_drop_target(self, dragged_item):
        center = dragged_item.mapToScene(dragged_item.boundingRect().center())
        target = self.node_item_at(center, exclude=dragged_item)
        for it in self.items():
            if isinstance(it, NodeItem):
                it.is_drop_target = (it is target)
                it.update()

    def finish_drag(self, dragged_item):
        node = dragged_item.node
        center = dragged_item.mapToScene(dragged_item.boundingRect().center())
        target = self.node_item_at(center, exclude=dragged_item)

        for it in self.items():
            if isinstance(it, NodeItem):
                it.is_drop_target = False
                it.update()

        if target is not None and node.parent is not None:
            t = target.node
            if t is not node and not is_descendant_of(t, node):
                node.parent.children.remove(node)
                t.add(node)
                t.collapsed = False
        self.rebuild()

    def node_item_at(self, scene_pos, exclude=None):
        for it in self.items(scene_pos):
            if isinstance(it, NodeItem) and it is not exclude:
                return it
        return None

    # ---------- 动作 5：空白双击新建 ----------
    def new_node(self):
        name, ok = QInputDialog.getText(None, "新建节点", "节点名称：")
        if not ok or not name.strip():
            return
        parent = self.selected_node
        if parent is None or parent is self.root:
            parent = self.root
        child = parent.add(MindNode(name.strip()))
        parent.collapsed = False
        self.selected_node = child
        self.rebuild()


# ---------------------------------------------------------------- 视图
class CanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))

        self._panning = False
        self._pan_start = QPoint()
        self._pan_scroll = (0, 0)

    def _node_at(self, view_pos):
        for it in self.items(view_pos):
            if isinstance(it, NodeItem):
                return it
        return None

    # ---------- 动作 2：滚轮缩放 ----------
    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d == 0:
            return
        f = 1.15 if d > 0 else 1 / 1.15
        self.scale(f, f)
        event.accept()

    # ---------- 动作 3：空白拖动平移 ----------
    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._node_at(event.position().toPoint()) is None):
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._pan_scroll = (self.horizontalScrollBar().value(),
                                self.verticalScrollBar().value())
            self.setCursor(Qt.ClosedHandCursor)
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
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- 动作 5：空白双击新建 ----------
    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._node_at(event.position().toPoint()) is None):
            self.scene().new_node()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ---------------------------------------------------------------- 窗口
class Demo(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M0 路线 B · QGraphicsScene 自绘")
        self.resize(1100, 700)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel(HINT))

        self.canvas = Canvas()
        self.canvas.set_root(sample_tree())
        self.view = CanvasView(self.canvas)
        layout.addWidget(self.view)

        self.setCentralWidget(central)
        self.view.centerOn(0, 0)


def main():
    app = QApplication(sys.argv)
    w = Demo()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
