# -*- coding: utf-8 -*-
"""导图画布：QGraphicsScene + QGraphicsItem 自绘（M0 定的路线 B）。

方向：**左→右**。深度决定横向位置，同层兄弟在纵向依次排开，
父节点的纵向位置 = 它第一个子节点与最后一个子节点的中点
（也就是规格里的「父节点垂直居中于子节点之间」）。

本模块只管画布机制（布局 / 命中 / 拖动 / 缩放 / 平移），
不弹任何对话框、不认识 mock_data —— 节点对象是鸭子类型的，
只需要有 name / kind / children / parent / collapsed 这几个属性。
布局结果（_w/_h/_x/_y）由本模块挂在节点对象上，是临时计算值。
"""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
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
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

# 改这里可以切换布局方向。当前只实现了 "LR"（左→右）。
ORIENTATION = "LR"

NODE_H = 34.0
NODE_MIN_W = 92.0
PAD_X = 18.0
H_GAP = 62.0      # 相邻两列之间的横向间距
V_GAP = 16.0      # 同列相邻节点之间的纵向间距

NODE_FONT = QFont("Microsoft YaHei", 10)
TOPIC_FONT = QFont("Microsoft YaHei", 10, QFont.Bold)

C_TOPIC_FILL = QColor("#eef7f1")
C_TOPIC_LINE = QColor("#2e8b57")
C_VIDEO_FILL = QColor("#ffffff")
C_VIDEO_LINE = QColor("#94a3b8")
C_SEL_FILL = QColor("#dbeafe")
C_DROP_LINE = QColor("#ef4444")
C_TEXT = QColor("#0f172a")
C_EDGE = QColor("#b6c2cf")


# --------------------------------------------------------------------------
# 节点图元
# --------------------------------------------------------------------------
class NodeItem(QGraphicsItem):
    def __init__(self, node, canvas):
        super().__init__()
        self.node = node
        self.canvas = canvas
        self.w = getattr(node, "_w", NODE_MIN_W)
        self.h = getattr(node, "_h", NODE_H)
        self.is_drop_target = False
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setPos(getattr(node, "_x", 0.0), getattr(node, "_y", 0.0))

    def boundingRect(self):
        return QRectF(-self.w / 2.0, -self.h / 2.0, self.w, self.h)

    def _is_collapsed_with_children(self):
        return bool(self.node.collapsed and self.node.children)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)

        if self.node.is_topic():
            painter.setBrush(QBrush(C_SEL_FILL if self.isSelected() else C_TOPIC_FILL))
        else:
            painter.setBrush(QBrush(C_SEL_FILL if self.isSelected() else C_VIDEO_FILL))

        if self.is_drop_target:
            painter.setPen(QPen(C_DROP_LINE, 2.6))
        else:
            color = C_TOPIC_LINE if self.node.is_topic() else C_VIDEO_LINE
            pen = QPen(color, 1.5)
            # 折叠(且确实有子节点) -> 虚线，替代 "＋N" 徽标
            if self._is_collapsed_with_children():
                pen.setStyle(Qt.DashLine)
                pen.setWidthF(1.3)
            painter.setPen(pen)
        painter.drawPath(path)

        painter.setPen(QPen(C_TEXT))
        painter.setFont(TOPIC_FONT if self.node.is_topic() else NODE_FONT)
        painter.drawText(r, Qt.AlignCenter, self.node.name)

    # ---- 交互 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.canvas.view.node_context_menu.emit(
                self.node, event.screenPos().toPoint())
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self.canvas.selected_node = self.node
        self.canvas.view.node_clicked.emit(self.node)
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


# --------------------------------------------------------------------------
# 画布
# --------------------------------------------------------------------------
class Canvas(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = None
        self.view = None
        self.selected_node = None

    # ---------------- 布局 ----------------
    def set_root(self, root):
        self.root = root
        self.rebuild()

    def rebuild(self):
        if ORIENTATION != "LR":
            raise NotImplementedError(f"未实现的布局方向: {ORIENTATION}")
        keep = self.selected_node
        self.clear()
        if self.root is None:
            return
        fm = QFontMetricsF(NODE_FONT)
        self._measure(self.root, fm)
        xs = self._column_x()
        self._place(self.root, 0, xs, 0.0)
        self._create_items(self.root)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-500, -500, 500, 500))
        if keep is not None:
            self.selected_node = keep
            if getattr(keep, "_item", None) is not None:
                keep._item.setSelected(True)

    def _measure(self, node, fm):
        node._w = max(NODE_MIN_W, fm.horizontalAdvance(node.name) + 2 * PAD_X)
        node._h = NODE_H
        for c in node.children:
            self._measure(c, fm)

    def _column_x(self):
        """每一层（深度）的左边缘 x。"""
        widths = {}

        def walk(n, d):
            widths[d] = max(widths.get(d, 0.0), n._w)
            if n.collapsed:
                return
            for c in n.children:
                walk(c, d + 1)

        walk(self.root, 0)
        xs, cur = {}, 0.0
        for d in sorted(widths):
            xs[d] = cur
            cur += widths[d] + H_GAP
        return xs

    def _place(self, node, depth, xs, y):
        """后序：先摆子树拿到纵向游标，再把父节点放在首末子节点的中点。"""
        if node.collapsed or not node.children:
            node._y = y + node._h / 2.0
            y += node._h + V_GAP
        else:
            for c in node.children:
                y = self._place(c, depth + 1, xs, y)
            node._y = (node.children[0]._y + node.children[-1]._y) / 2.0
        node._x = xs[depth] + node._w / 2.0
        return y

    def _create_items(self, node):
        item = NodeItem(node, self)
        node._item = item
        self.addItem(item)
        if node.collapsed:
            return
        for c in node.children:
            self.addItem(self._make_edge(node, c))
            self._create_items(c)

    @staticmethod
    def _make_edge(parent, child):
        """父节点右边缘中点 -> 子节点左边缘中点，三次贝塞尔。"""
        p1 = QPointF(parent._x + parent._w / 2.0, parent._y)
        p2 = QPointF(child._x - child._w / 2.0, child._y)
        dx = p2.x() - p1.x()
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(QPointF(p1.x() + dx * 0.5, p1.y()),
                     QPointF(p2.x() - dx * 0.5, p2.y()),
                     p2)
        e = QGraphicsPathItem(path)
        e.setPen(QPen(C_EDGE, 1.5))
        e.setZValue(1)
        return e

    # ---------------- 交互 ----------------
    def toggle_collapse(self, node):
        if not node.children:
            return
        node.collapsed = not node.collapsed
        self.selected_node = node
        self.rebuild()

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
            if t is not node and not _is_descendant_of(t, node):
                node.parent.children.remove(node)
                t.add(node)
                t.collapsed = False
        self.rebuild()

    def node_item_at(self, scene_pos, exclude=None):
        for it in self.items(scene_pos):
            if isinstance(it, NodeItem) and it is not exclude:
                return it
        return None

    def add_child(self, parent, child):
        """把已造好的 child 挂到 parent 下。节点对象由调用方创建，
        画布不认识具体的数据类（保持鸭子类型）。"""
        if parent is None or parent.is_video():
            parent = self.root
        parent.add(child)
        parent.collapsed = False
        self.selected_node = child
        self.rebuild()
        return child

    def remove_node(self, node):
        """删除节点（根节点不动）。返回是否删掉了。"""
        if node is None or node.parent is None:
            return False
        node.parent.children.remove(node)
        self.selected_node = node.parent
        self.rebuild()
        return True

    def rename_node(self, node, new_name):
        if node is None or not new_name:
            return
        node.name = new_name
        self.rebuild()


def _is_descendant_of(candidate, node):
    p = candidate.parent
    while p is not None:
        if p is node:
            return True
        p = p.parent
    return False


# --------------------------------------------------------------------------
# 视图
# --------------------------------------------------------------------------
class CanvasView(QGraphicsView):
    node_clicked = Signal(object)                   # MindNode
    node_context_menu = Signal(object, QPoint)      # MindNode, 全局坐标
    blank_double_clicked = Signal(QPointF)          # 场景坐标

    def __init__(self, scene):
        super().__init__(scene)
        scene.view = self
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor("#fbfcfd")))
        self.setFrameShape(QGraphicsView.NoFrame)
        self._panning = False
        self._pan_start = QPoint()
        self._pan_scroll = (0, 0)

    def _node_at(self, view_pos):
        for it in self.items(view_pos):
            if isinstance(it, NodeItem):
                return it
        return None

    # 滚轮 -> 缩放
    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d == 0:
            return
        f = 1.14 if d > 0 else 1 / 1.14
        self.scale(f, f)
        event.accept()

    # 空白拖动 -> 平移
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

    # 空白双击 -> 新建节点
    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._node_at(event.position().toPoint()) is None):
            self.blank_double_clicked.emit(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
