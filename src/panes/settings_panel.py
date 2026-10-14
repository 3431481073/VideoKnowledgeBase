# -*- coding: utf-8 -*-
"""设置面板：四项 + 恢复默认 / 保存。

本轮**只写内存，不落盘**。原因是有一条真实的数据风险：
    保存时若把 clean_api_key 字段的当前值（可能是空）写回 config.json，
    会覆盖掉真实的 API Key —— load_config() 有"空串视为未设置"的保护，
    但 save_config() 是直接写的，这条路径没保护。
下一轮接 config 时会先给 save_config 补上空值保护再接。

规格：模型固定 medium，不暴露 -> 这里没有转写模型选项。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SettingsPanel(QWidget):
    saved = Signal(dict)
    closed = Signal()

    #: (键, 标签, 是否多行)
    FIELDS = [
        ("clean_url", "清洗 URL", False),
        ("clean_model", "清洗 Model", False),
        ("clean_api_key", "清洗 API Key", False),
        ("clean_prompt", "清洗提示词", True),
    ]

    def __init__(self, defaults=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPanel")
        self._defaults = dict(defaults or {})
        self._editors = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)

        # ---- 顶部：标题 + 返回 ----
        head = QHBoxLayout()
        title = QLabel("设置")
        title.setStyleSheet("font-size:15px; font-weight:600;")
        head.addWidget(title)
        head.addStretch(1)
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setFixedWidth(78)
        self.back_btn.clicked.connect(self.closed.emit)
        head.addWidget(self.back_btn)
        outer.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e5e7eb;")
        outer.addWidget(line)

        # ---- 四个字段 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        form = QVBoxLayout(host)
        form.setContentsMargins(2, 2, 2, 2)
        form.setSpacing(10)

        for key, label, multiline in self.FIELDS:
            lab = QLabel(label)
            lab.setStyleSheet("font-size:12px; color:#475569;")
            form.addWidget(lab)
            if multiline:
                ed = QTextEdit()
                ed.setMinimumHeight(150)
                ed.setStyleSheet("font-size:12px;")
            else:
                ed = QLineEdit()
                ed.setStyleSheet("font-size:12px; padding:4px;")
            self._editors[key] = ed
            form.addWidget(ed)

        form.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        # ---- 底部：恢复默认 / 保存 ----
        foot = QHBoxLayout()
        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.clicked.connect(self.restore_defaults)
        foot.addWidget(self.reset_btn)
        foot.addStretch(1)
        self.save_btn = QPushButton("保存")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        foot.addWidget(self.save_btn)
        outer.addLayout(foot)

        self.set_values(self._defaults)

    # ------------------------------------------------------------------ 对外
    def set_values(self, values):
        for key, _label, multiline in self.FIELDS:
            if key not in self._editors:
                continue
            v = str(values.get(key, ""))
            ed = self._editors[key]
            if multiline:
                ed.setPlainText(v)
            else:
                ed.setText(v)

    def values(self):
        out = {}
        for key, _label, multiline in self.FIELDS:
            ed = self._editors.get(key)
            if ed is None:
                continue
            out[key] = ed.toPlainText() if multiline else ed.text()
        return out

    def restore_defaults(self):
        self.set_values(self._defaults)

    # ------------------------------------------------------------------ 内部
    def _on_save(self):
        self.saved.emit(self.values())
