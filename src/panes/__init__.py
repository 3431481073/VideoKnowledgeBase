# -*- coding: utf-8 -*-
"""四个窗格。

M2 的占位基类 `PlaceholderPane` 已随本轮真实现删除（无任何引用）。
四个 pane 之间**互不认识**，全部经 main_window.py 接线。
"""

from .tree_pane import TreePane
from .content_pane import ContentPane
from .done_pane import DonePane
from .pending_pane import PendingPane

__all__ = ["TreePane", "ContentPane", "DonePane", "PendingPane"]
