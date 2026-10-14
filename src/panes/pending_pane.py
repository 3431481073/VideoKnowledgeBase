# -*- coding: utf-8 -*-
"""右下格：待处理区 + 设置面板（同一格内切换）。

顶部窄栏三个按钮：● 打开摄像头 / ＋ 导入视频 / ⚙ 设置。
列表每条：视频名 + 「转写」「整理」两个状态标签 + 右侧「处理」按钮。

本轮进度是**模拟的**（QTimer 逐格推进），不接任何真实转写/清洗。
每条一个独立定时器，多条可同时跑。
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .settings_panel import SettingsPanel

TICK_MS = 90
TRANSCRIBE_STEP = 7      # 约 15 拍 = 1.35s
CLEAN_STEP = 9           # 约 12 拍 = 1.08s

PAGE_LIST, PAGE_SETTINGS = 0, 1

_GLYPH_STYLE = "QPushButton { font-size:13px; padding:4px 10px; }"


class _PendingRow(QWidget):
    process_clicked = Signal(object)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(2)
        self.name_label = QLabel(item.video_name)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("font-size:13px; color:#0f172a;")
        left.addWidget(self.name_label)

        tags = QHBoxLayout()
        tags.setSpacing(6)
        self.trans_label = QLabel()
        self.clean_label = QLabel()
        for lb in (self.trans_label, self.clean_label):
            lb.setAlignment(Qt.AlignCenter)
            tags.addWidget(lb)
        tags.addStretch(1)
        left.addLayout(tags)
        lay.addLayout(left, 1)

        self.btn = QPushButton("处理")
        self.btn.setFixedWidth(62)
        self.btn.clicked.connect(lambda: self.process_clicked.emit(self.item))
        lay.addWidget(self.btn, 0, Qt.AlignVCenter)

        self.refresh()

    def refresh(self):
        it = self.item
        if it.stage == "idle":
            self._set_tag(self.trans_label, "转写 —", "#94a3b8", "#f1f5f9")
            self._set_tag(self.clean_label, "整理 —", "#94a3b8", "#f1f5f9")
            self.btn.setEnabled(True)
            self.btn.setText("处理")
        elif it.stage == "transcribing":
            self._set_tag(self.trans_label, f"转写 {it.transcribe_pct}%", "#1d4ed8", "#dbeafe")
            self._set_tag(self.clean_label, "整理 —", "#94a3b8", "#f1f5f9")
            self.btn.setEnabled(False)
            self.btn.setText("转写中")
        elif it.stage == "cleaning":
            self._set_tag(self.trans_label, "转写 ✓", "#047857", "#d1fae5")
            self._set_tag(self.clean_label, f"整理 {it.clean_pct}%", "#1d4ed8", "#dbeafe")
            self.btn.setEnabled(False)
            self.btn.setText("整理中")

    @staticmethod
    def _set_tag(label, text, fg, bg):
        label.setText(text)
        label.setStyleSheet(
            f"font-size:11px; color:{fg}; background:{bg};"
            f"border-radius:3px; padding:1px 7px;")


class PendingPane(QWidget):
    item_finished = Signal(object)      # MockItem
    settings_saved = Signal(dict)
    status_message = Signal(str)

    def __init__(self, items=None, item_factory=None, settings_defaults=None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("PendingPane")
        self.items = list(items or [])
        self._item_factory = item_factory
        self._rows = {}
        self._list_items = {}
        self._timers = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        # ---------------- 页 0：待处理列表 ----------------
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        bar = QWidget()
        bar.setStyleSheet("background:#f8fafc;")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(8, 5, 8, 5)
        bh.setSpacing(6)
        self.cam_btn = QPushButton("● 打开摄像头")
        self.import_btn = QPushButton("＋ 导入视频")
        self.gear_btn = QPushButton("⚙")
        for b in (self.cam_btn, self.import_btn, self.gear_btn):
            b.setStyleSheet(_GLYPH_STYLE)
            bh.addWidget(b)
        bh.addStretch(1)
        self.gear_btn.setToolTip("设置")
        self.gear_btn.setFixedWidth(38)
        self.cam_btn.clicked.connect(self._on_camera)
        self.import_btn.clicked.connect(self._on_import)
        self.gear_btn.clicked.connect(self.open_settings)
        pv.addWidget(bar)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e5e7eb;")
        pv.addWidget(line)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setStyleSheet("QListWidget::item { border-bottom:1px solid #f1f5f9; }")
        pv.addWidget(self.list, 1)
        self.stack.addWidget(page)

        # ---------------- 页 1：设置 ----------------
        self.settings = SettingsPanel(defaults=settings_defaults)
        self.settings.saved.connect(self._on_settings_saved)
        self.settings.closed.connect(lambda: self.stack.setCurrentIndex(PAGE_LIST))
        self.stack.addWidget(self.settings)

        self._reload_list()

    # ------------------------------------------------------------------ 列表
    def _reload_list(self):
        self.list.clear()
        self._rows.clear()
        self._list_items.clear()
        for item in self.items:
            self._append_row(item)

    def _append_row(self, item):
        row = _PendingRow(item)
        row.process_clicked.connect(self.start_processing)
        li = QListWidgetItem()
        li.setSizeHint(row.sizeHint())
        self.list.addItem(li)
        self.list.setItemWidget(li, row)
        self._rows[item] = row
        self._list_items[item] = li

    def _remove_row(self, item):
        li = self._list_items.pop(item, None)
        if li is not None:
            idx = self.list.row(li)
            self.list.takeItem(idx)
        self._rows.pop(item, None)

    # ------------------------------------------------------------------ 三个按钮
    def _on_camera(self):
        # 规格未定义本轮的摄像头行为，且本轮不接后端 -> 只给提示，不做假动作
        self.status_message.emit("摄像头接入下一轮做（本轮是纯界面原型）")

    def _on_import(self):
        if self._item_factory is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv);;所有文件 (*.*)")
        if not files:
            return
        import os
        for path in files:
            item = self._item_factory(os.path.basename(path))
            self.items.append(item)
            self._append_row(item)
        self.status_message.emit(f"已导入 {len(files)} 个视频（默认不处理）")

    def open_settings(self):
        self.stack.setCurrentIndex(PAGE_SETTINGS)

    # ------------------------------------------------------------------ 设置
    def _on_settings_saved(self, values):
        # 本轮只写内存，不落盘（保护真实 API Key，见 settings_panel 模块注释）
        self.settings_saved.emit(values)
        self.stack.setCurrentIndex(PAGE_LIST)
        self.status_message.emit("设置已保存（本轮仅内存，未落盘）")

    # ------------------------------------------------------------------ 处理
    def start_processing(self, item):
        if item.stage != "idle":
            return
        item.stage = "transcribing"
        item.transcribe_pct = 0
        item.clean_pct = 0
        self._rows[item].refresh()

        t = QTimer(self)
        t.setInterval(TICK_MS)
        t.timeout.connect(lambda it=item: self._tick(it))
        self._timers[item] = t
        t.start()

    def _tick(self, item):
        if item.stage == "transcribing":
            item.transcribe_pct = min(100, item.transcribe_pct + TRANSCRIBE_STEP)
            if item.transcribe_pct >= 100:
                item.stage = "cleaning"
                item.clean_pct = 0
        elif item.stage == "cleaning":
            item.clean_pct = min(100, item.clean_pct + CLEAN_STEP)
            if item.clean_pct >= 100:
                self._finish(item)
                return

        row = self._rows.get(item)
        if row is not None:
            row.refresh()

    def _finish(self, item):
        t = self._timers.pop(item, None)
        if t is not None:
            t.stop()
            t.deleteLater()
        item.stage = "done"
        item.transcribe_pct = 100
        item.clean_pct = 100
        self._remove_row(item)
        if item in self.items:
            self.items.remove(item)
        self.item_finished.emit(item)

    # ------------------------------------------------------------------ 测试辅助
    def pending_count(self):
        return self.list.count()
