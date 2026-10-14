# -*- coding: utf-8 -*-
"""左上格：导图窗格。

画布机制在 mind_map.py；本模块只负责 Qt 侧的事：
右键菜单、输入框、删除确认，以及对外发 node_selected 信号。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .mind_map import Canvas, CanvasView


class TreePane(QWidget):
    node_selected = Signal(object)     # MindNode

    def __init__(self, root=None, node_factory=None, parent=None):
        super().__init__(parent)
        self.setObjectName("TreePane")
        self._node_factory = node_factory

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = Canvas(self)
        self.view = CanvasView(self.canvas)
        layout.addWidget(self.view)

        self.view.node_clicked.connect(self._on_node_clicked)
        self.view.node_context_menu.connect(self._on_context_menu)
        self.view.blank_double_clicked.connect(self._on_blank_double_clicked)

        self.set_root(root)

    # ------------------------------------------------------------------ 数据
    def set_root(self, root):
        self.canvas.set_root(root)
        # 默认把根设为选中，这样「空白双击新建」有个合理的落点
        self.canvas.selected_node = root
        if root is not None:
            self.node_selected.emit(root)

    def root(self):
        return self.canvas.root

    def refresh_node(self, node):
        """外部（文章面板）改了节点名之后调用，重画导图。"""
        self.canvas.rebuild()

    def select_node(self, node):
        self.canvas.selected_node = node
        if getattr(node, "_item", None) is not None:
            node._item.setSelected(True)
        self.node_selected.emit(node)

    # ------------------------------------------------------------------ 画布回调
    def _on_node_clicked(self, node):
        self.node_selected.emit(node)

    def _new_node(self, parent):
        if self._node_factory is None:
            return
        name, ok = QInputDialog.getText(self, "新建节点", "节点名称：")
        if not ok or not name.strip():
            return
        child = self._node_factory(name.strip(), "topic")
        self.canvas.add_child(parent, child)
        self.node_selected.emit(child)

    def _on_blank_double_clicked(self, _scene_pos):
        parent = self.canvas.selected_node or self.canvas.root
        self._new_node(parent)

    def _on_context_menu(self, node, global_pos):
        if node is None:
            return
        self.canvas.selected_node = node
        if getattr(node, "_item", None) is not None:
            node._item.setSelected(True)

        menu = QMenu(self)
        act_rename = menu.addAction("重命名")
        act_subtopic = menu.addAction("新建子主题")
        act_delete = menu.addAction("删除")

        # 视频节点下挂主题没有意义 -> 禁用；根节点不能删
        act_subtopic.setEnabled(node.is_topic())
        act_delete.setEnabled(node.parent is not None)

        action = menu.exec(global_pos)
        if action is None:
            return
        if action == act_rename:
            self._rename(node)
        elif action == act_subtopic:
            self._new_node(node)
        elif action == act_delete:
            self._delete(node)

    def _rename(self, node):
        name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=node.name)
        if not ok or not name.strip():
            return
        self.canvas.rename_node(node, name.strip())
        self.node_selected.emit(node)

    def _delete(self, node):
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定删除「{node.name}」及其全部子节点吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self.canvas.remove_node(node)
        self.node_selected.emit(self.canvas.selected_node)
