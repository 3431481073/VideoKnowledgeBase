import sys
import os
import json
import zipfile
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QMenu, QStatusBar,
    QDialog, QDialogButtonBox, QTextEdit, QSplitter, QTreeWidget,
    QTreeWidgetItem, QLabel, QSlider, QStyle, QGraphicsView,
    QGraphicsScene, QFrame, QHeaderView, QAbstractItemView,
    QToolButton, QWidgetAction, QLineEdit, QScrollArea, QPlainTextEdit,
    QSizePolicy
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtCore import Qt, QThread, Signal, QObject, QUrl, QDateTime, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from transcriber import transcribe_video
from ai_processor import process_segments
from knowledge_browser import KnowledgeBrowserWindow
from knowledge_tree import load_tree
from workspace import (
    load_workspace as load_workspace_from_file,
    save_workspace as save_workspace_to_file,
    VideoItem,
    format_size, format_time, sanitize_filename
)

DEEPSEEK_API_KEY = ""

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw_transcripts")
AI_DIR = os.path.join(BASE_DIR, "data", "ai_processed")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(AI_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


# ---------- 后台任务 ----------
class BatchTranscribeWorker(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(int, list)
    all_done = Signal()
    error = Signal(str)

    def __init__(self, video_paths):
        super().__init__()
        self.video_paths = video_paths

    def run(self):
        try:
            total = len(self.video_paths)
            for idx, path in enumerate(self.video_paths):
                self.progress.emit(idx + 1, total, os.path.basename(path))
                segments = transcribe_video(path)
                self.item_done.emit(idx, segments)
            self.all_done.emit()
        except Exception as e:
            self.error.emit(str(e))


class BatchAIProcessWorker(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(int, dict)
    all_done = Signal()
    error = Signal(str)

    def __init__(self, tasks, api_key):
        super().__init__()
        self.tasks = tasks
        self.api_key = api_key

    def run(self):
        try:
            total = len(self.tasks)
            for idx, (segments_file, _) in enumerate(self.tasks):
                self.progress.emit(idx + 1, total, os.path.basename(segments_file))
                with open(segments_file, "r", encoding="utf-8") as f:
                    segments = json.load(f)
                result = process_segments(segments, self.api_key)
                self.item_done.emit(idx, result)
            self.all_done.emit()
        except Exception as e:
            self.error.emit(str(e))


# ---------- 编辑转写对话框 ----------
class EditTranscriptDialog(QDialog):
    def __init__(self, parent, video_item):
        super().__init__(parent)
        self.video_item = video_item
        self.setWindowTitle(f"编辑转写 - {video_item.name}")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        raw_file = video_item.get_raw_text_path()
        if os.path.exists(raw_file):
            with open(raw_file, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())
        layout.addWidget(self.text_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        raw_file = self.video_item.get_raw_text_path()
        try:
            with open(raw_file, "w", encoding="utf-8") as f:
                f.write(self.text_edit.toPlainText())
            self.video_item.transcribed = True
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "警告", f"保存失败：{e}")


# ---------- 主窗口 ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频知识库")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))
        self.move(screen.x() + (screen.width() - self.width()) // 2,
                  screen.y() + (screen.height() - self.height()) // 2)

        self.top_items = []
        self.last_import_dir = ""
        self.current_playing_video = None
        self.rotation_angle = 0
        self._skip_selection_preview = False

        self.worker_thread = None
        self.ai_batch_worker_thread = None

        self._build_ui()
        self.load_workspace()

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 顶部按钮区
        top_layout = QHBoxLayout()
        self.import_btn = QPushButton("导入视频")
        self.import_btn.clicked.connect(self.import_videos)
        top_layout.addWidget(self.import_btn)

        self.transcribe_btn = QPushButton("批量转写")
        self.transcribe_btn.clicked.connect(self.transcribe_selected)
        top_layout.addWidget(self.transcribe_btn)

        self.ai_batch_btn = QPushButton("批量AI整理")
        self.ai_batch_btn.clicked.connect(self.batch_ai_process)
        top_layout.addWidget(self.ai_batch_btn)

        self.browse_btn = QPushButton("知识库")
        self.browse_btn.clicked.connect(self.open_knowledge_browser)
        top_layout.addWidget(self.browse_btn)

        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # 中间分割：左侧树形表格，右侧视频预览
        splitter = QSplitter(Qt.Horizontal)

        # 左侧树形表格
        self.tree_widget = QTreeWidget()
        self.tree_widget.setColumnCount(6)
        self.tree_widget.setHeaderLabels(
            ["文件名", "创建时间", "大小", "转写", "AI", "播放"])
        self.tree_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree_widget.setSelectionBehavior(QAbstractItemView.SelectRows)  # 整行选中
        self.tree_widget.setRootIsDecorated(False)  # 隐藏展开箭头占位
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.tree_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree_widget.itemClicked.connect(self.on_item_clicked)
        self.tree_widget.itemSelectionChanged.connect(self.on_selection_changed)
        self.tree_widget.setUniformRowHeights(True)

        header = self.tree_widget.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # 文件名列拉伸
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 创建时间
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 大小
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.tree_widget.setColumnWidth(1, 160)  # 创建时间加宽
        self.tree_widget.setColumnWidth(2, 100)  # 大小
        self.tree_widget.setColumnWidth(3, 50)
        self.tree_widget.setColumnWidth(4, 50)
        self.tree_widget.setColumnWidth(5, 100)  # 播放宽度与大小相同
        for i in range(6):
            self.tree_widget.headerItem().setTextAlignment(i, Qt.AlignCenter)

        self.tree_widget.viewport().setMouseTracking(True)
        self.tree_widget.viewport().installEventFilter(self)

        splitter.addWidget(self.tree_widget)

        # 右侧视频预览区
        self.preview_panel = QWidget()
        self.preview_panel.setMaximumWidth(380)
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(5, 5, 5, 5)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.video_scene = QGraphicsScene()
        self.video_item = QGraphicsVideoItem()
        self.video_scene.addItem(self.video_item)
        self.video_view = QGraphicsView(self.video_scene)
        self.video_view.setFrameShape(QFrame.NoFrame)
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.video_view.setMinimumSize(320, 180)
        self.player.setVideoOutput(self.video_item)
        preview_layout.addWidget(self.video_view, stretch=1)

        controls_layout = QHBoxLayout()
        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setFixedWidth(30)
        self.play_pause_btn.clicked.connect(self.toggle_preview_play)
        controls_layout.addWidget(self.play_pause_btn)

        self.preview_slider = QSlider(Qt.Horizontal)
        self.preview_slider.setRange(0, 0)
        self.preview_slider.sliderMoved.connect(self.preview_seek)
        self.preview_slider.sliderPressed.connect(self.preview_slider_pressed)
        controls_layout.addWidget(self.preview_slider, 1)

        self.volume_btn = QToolButton()
        self.volume_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.volume_btn.setPopupMode(QToolButton.InstantPopup)
        self.volume_menu = QMenu(self)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(self.preview_set_volume)
        volume_action = QWidgetAction(self.volume_menu)
        volume_action.setDefaultWidget(self.volume_slider)
        self.volume_menu.addAction(volume_action)
        self.volume_btn.setMenu(self.volume_menu)
        controls_layout.addWidget(self.volume_btn)

        self.preview_time_label = QLabel("00:00 / 00:00")
        self.preview_time_label.setFixedWidth(90)
        controls_layout.addWidget(self.preview_time_label)

        self.rotate_btn = QPushButton("旋转")
        self.rotate_btn.setFixedWidth(50)
        self.rotate_btn.clicked.connect(self.rotate_video)
        controls_layout.addWidget(self.rotate_btn)

        preview_layout.addLayout(controls_layout)
        splitter.addWidget(self.preview_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1000, 380])

        main_layout.addWidget(splitter)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        # 播放器信号
        self.player.positionChanged.connect(self.on_preview_position_changed)
        self.player.durationChanged.connect(self.on_preview_duration_changed)
        self.player.playbackStateChanged.connect(self.on_preview_state_changed)
        self.player.errorOccurred.connect(self.on_preview_error)
        self.video_item.nativeSizeChanged.connect(self.on_video_native_size_changed)
        self.video_view.resizeEvent = self.on_video_view_resize

    # ---------- 事件过滤器 ----------
    def eventFilter(self, obj, event):
        if obj == self.tree_widget.viewport() and event.type() == QEvent.MouseMove:
            pos = event.position().toPoint()
            item = self.tree_widget.itemAt(pos)
            if item:
                col = self.tree_widget.columnAt(pos.x())
                if col in (3, 4):  # 转写、AI 列
                    self.tree_widget.setCursor(Qt.PointingHandCursor)
                    return True
            self.tree_widget.setCursor(Qt.ArrowCursor)
        elif obj == self.video_view.viewport() and event.type() == QEvent.MouseButtonPress:
            self.toggle_preview_play()
            return True
        return super().eventFilter(obj, event)

    # ---------- 工作区 ----------
    def load_workspace(self):
        self.top_items, self.last_import_dir = load_workspace_from_file()
        self.refresh_tree()
        self.statusBar().showMessage(f"已恢复工作区，共 {len(self.top_items)} 个顶层项目")

    def save_workspace(self):
        save_workspace_to_file(self.top_items, self.last_import_dir)

    def refresh_tree(self):
        self.tree_widget.clear()
        for item in self.top_items:
            tree_item = self._create_tree_item(item)
            self.tree_widget.addTopLevelItem(tree_item)
        self._apply_column_widths()

    def _apply_column_widths(self):
        self.tree_widget.setColumnWidth(1, 160)
        self.tree_widget.setColumnWidth(2, 100)
        self.tree_widget.setColumnWidth(3, 50)
        self.tree_widget.setColumnWidth(4, 50)
        self.tree_widget.setColumnWidth(5, 100)
        # 文件名列（0）会自动拉伸，无需设置固定宽度

    def _create_tree_item(self, item):
        if isinstance(item, VideoItem):
            node = QTreeWidgetItem()
            node.setText(0, item.name)
            node.setText(1, QDateTime.fromSecsSinceEpoch(int(item.created)).toString("yyyy-MM-dd hh:mm"))
            node.setText(2, format_size(item.size))
            node.setText(3, "✅" if item.transcribed else "❌")
            node.setText(4, "✅" if item.ai_processed else "❌")
            node.setText(5, "🔊" if item.file_path == self.current_playing_video else "")
            node.setData(0, Qt.UserRole, item)
            for col in range(6):
                node.setTextAlignment(col, Qt.AlignCenter)
            return node
        else:
            return None

    # ---------- 导入视频 ----------
    def import_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", self.last_import_dir,
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv);;所有文件 (*.*)"
        )
        if not files:
            return
        self.last_import_dir = os.path.dirname(files[0])
        added_count = 0
        for file_path in files:
            if self._is_video_in_workspace(file_path):
                continue
            video_item = VideoItem(file_path)
            self.top_items.append(video_item)
            added_count += 1
        if added_count > 0:
            self.top_items.sort(key=lambda x: x.created, reverse=True)
            self.refresh_tree()
            self.save_workspace()
        self.statusBar().showMessage(f"已导入 {added_count} 个新视频")

    def _is_video_in_workspace(self, file_path):
        return any(isinstance(item, VideoItem) and item.file_path == file_path for item in self.top_items)

    # ---------- 视频预览 ----------
    def on_selection_changed(self):
        if self._skip_selection_preview:
            return
        selected = self.tree_widget.selectedItems()
        if not selected:
            return
        item = selected[0]
        data = item.data(0, Qt.UserRole)
        if isinstance(data, VideoItem):
            self.load_preview_video(data.file_path)

    def on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if isinstance(data, VideoItem):
            self.load_preview_video(data.file_path)

    def on_item_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if not isinstance(data, VideoItem):
            return
        if column == 3:  # 转写列
            dialog = EditTranscriptDialog(self, data)
            if dialog.exec() == QDialog.Accepted:
                self.refresh_tree()
                self.save_workspace()
        elif column == 4:  # AI 整理列
            if data.ai_processed:
                QMessageBox.information(self, "提示", "该视频已完成 AI 整理。可在知识库中查看。")
            else:
                QMessageBox.information(self, "提示", "该视频尚未进行 AI 整理，请先执行批量 AI 整理。")

    def load_preview_video(self, video_path):
        if not video_path or not os.path.exists(video_path):
            return
        url = QUrl.fromLocalFile(video_path)
        self.player.setSource(url)
        self.player.pause()
        self.current_playing_video = video_path
        self.update_playing_icon()

    def update_playing_icon(self):
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if isinstance(data, VideoItem):
                item.setText(5, "🔊" if data.file_path == self.current_playing_video else "")

    def fit_video_to_view(self):
        if self.video_item.boundingRect().width() <= 0 or self.video_item.boundingRect().height() <= 0:
            return
        view_size = self.video_view.viewport().size()
        video_size = self.video_item.boundingRect().size()
        scale = min(view_size.width() / video_size.width(), view_size.height() / video_size.height())
        new_size = video_size * scale
        self.video_item.setSize(new_size)
        self.video_item.setPos((view_size.width() - new_size.width()) / 2,
                               (view_size.height() - new_size.height()) / 2)
        scene_rect = self.video_item.boundingRect().translated(self.video_item.pos())
        self.video_scene.setSceneRect(scene_rect)
        self.video_view.setSceneRect(scene_rect)

    def on_video_native_size_changed(self, size):
        self.fit_video_to_view()

    def on_video_view_resize(self, event):
        super(QGraphicsView, self.video_view).resizeEvent(event)
        self.fit_video_to_view()

    def toggle_preview_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def preview_slider_pressed(self):
        width = self.preview_slider.width()
        pos = self.preview_slider.mapFromGlobal(self.cursor().pos()).x()
        if width > 0:
            value = self.preview_slider.minimum() + (self.preview_slider.maximum() - self.preview_slider.minimum()) * (
                    pos / width)
            self.preview_slider.setValue(int(value))
            self.player.setPosition(int(value))
            self.preview_time_label.setText(
                f"{format_time(int(value) / 1000)} / {format_time(self.player.duration() / 1000)}")

    def preview_seek(self, pos):
        self.player.setPosition(pos)

    def preview_set_volume(self, val):
        self.audio_output.setVolume(val / 100.0)

    def on_preview_position_changed(self, pos):
        self.preview_slider.setValue(pos)
        dur = self.player.duration()
        if dur > 0:
            self.preview_time_label.setText(f"{format_time(pos / 1000)} / {format_time(dur / 1000)}")
        else:
            self.preview_time_label.setText(f"{format_time(pos / 1000)} / 00:00")

    def on_preview_duration_changed(self, dur):
        self.preview_slider.setRange(0, dur)
        self.preview_time_label.setText(f"00:00 / {format_time(dur / 1000)}")

    def on_preview_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def on_preview_error(self, error, error_string):
        QMessageBox.warning(self, "播放错误", f"视频播放失败：{error_string}")

    def rotate_video(self):
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.video_item.setRotation(self.rotation_angle)
        self.video_item.setTransformOriginPoint(self.video_item.boundingRect().center())
        self.fit_video_to_view()

    # ---------- 转写 ----------
    def transcribe_selected(self):
        selected = self.tree_widget.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请至少选择一个条目进行转写。")
            return

        to_transcribe = []
        seen = set()
        for item in selected:
            data = item.data(0, Qt.UserRole)
            if isinstance(data, VideoItem) and not data.transcribed and data.file_path not in seen:
                to_transcribe.append(data.file_path)
                seen.add(data.file_path)

        if not to_transcribe:
            QMessageBox.information(self, "提示", "选中的条目都已转写，无需重复处理。")
            return

        self.transcribe_btn.setEnabled(False)
        self.statusBar().showMessage(f"正在批量转写 {len(to_transcribe)} 个视频...")

        self.worker_thread = QThread()
        self.worker = BatchTranscribeWorker(to_transcribe)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_transcribe_progress)
        self.worker.item_done.connect(self.on_transcribe_item_done)
        self.worker.all_done.connect(self.on_transcribe_all_done)
        self.worker.error.connect(self.on_transcribe_error)
        self.worker.all_done.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def on_transcribe_progress(self, idx, total, filename):
        self.statusBar().showMessage(f"正在处理 {idx}/{total}：{filename}")

    def on_transcribe_item_done(self, idx, segments):
        video_path = self.worker.video_paths[idx] if hasattr(self.worker, 'video_paths') else None
        if not video_path:
            return
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        raw_txt = os.path.join(RAW_DIR, base_name + ".txt")
        raw_json = os.path.join(RAW_DIR, base_name + "_segments.json")
        text = "".join(seg["text"] for seg in segments)
        with open(raw_txt, "w", encoding="utf-8") as f:
            f.write(text)
        with open(raw_json, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)

        self._update_video_status(video_path)
        self._refresh_tree_item_by_video(video_path)

    def _refresh_tree_item_by_video(self, video_path):
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if isinstance(data, VideoItem) and data.file_path == video_path:
                item.setText(3, "✅" if data.transcribed else "❌")
                item.setText(4, "✅" if data.ai_processed else "❌")
                break

    def on_transcribe_all_done(self):
        self.transcribe_btn.setEnabled(True)
        self.refresh_tree()
        self.save_workspace()
        self.statusBar().showMessage("批量转写完成")

    def on_transcribe_error(self, error_msg):
        self.transcribe_btn.setEnabled(True)
        QMessageBox.critical(self, "错误", f"转写失败：{error_msg}")

    def _update_video_status(self, video_path):
        for item in self.top_items:
            if isinstance(item, VideoItem) and item.file_path == video_path:
                item.refresh_status()
                break

    # ---------- AI 整理 ----------
    def batch_ai_process(self):
        selected = self.tree_widget.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请至少选择一个条目进行 AI 整理。")
            return

        missing = [item.data(0, Qt.UserRole).file_path for item in selected
                   if isinstance(item.data(0, Qt.UserRole), VideoItem) and not item.data(0, Qt.UserRole).transcribed]

        if missing:
            ret = QMessageBox.question(
                self,
                "存在未转写视频",
                f"有 {len(missing)} 个视频尚未转写。是否先自动转写，再继续 AI 整理？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if ret != QMessageBox.Yes:
                return
            QMessageBox.information(self, "提示", "请先点击“批量转写”完成转写，再执行 AI 整理。")
            return

        tasks = []
        for item in selected:
            data = item.data(0, Qt.UserRole)
            if isinstance(data, VideoItem):
                seg_file = data.get_segments_path()
                output_base = os.path.splitext(os.path.basename(data.file_path))[0]
                tasks.append((seg_file, output_base))

        if not tasks:
            QMessageBox.information(self, "提示", "没有可整理的转写数据。")
            return

        self.ai_batch_btn.setEnabled(False)
        self.statusBar().showMessage(f"正在批量 AI 整理 {len(tasks)} 个条目...")

        self.ai_batch_worker_thread = QThread()
        self.ai_batch_worker = BatchAIProcessWorker(tasks, DEEPSEEK_API_KEY)
        self.ai_batch_worker.moveToThread(self.ai_batch_worker_thread)

        self.ai_batch_worker_thread.started.connect(self.ai_batch_worker.run)
        self.ai_batch_worker.progress.connect(self.on_ai_batch_progress)
        self.ai_batch_worker.item_done.connect(self.on_ai_batch_item_done)
        self.ai_batch_worker.all_done.connect(self.on_ai_batch_all_done)
        self.ai_batch_worker.error.connect(self.on_ai_batch_error)
        self.ai_batch_worker.all_done.connect(self.ai_batch_worker_thread.quit)
        self.ai_batch_worker.error.connect(self.ai_batch_worker_thread.quit)
        self.ai_batch_worker_thread.finished.connect(self.ai_batch_worker.deleteLater)
        self.ai_batch_worker_thread.finished.connect(self.ai_batch_worker_thread.deleteLater)

        self.ai_batch_worker_thread.start()

    def on_ai_batch_progress(self, idx, total, filename):
        self.statusBar().showMessage(f"AI 整理 {idx}/{total}：{filename}")

    def on_ai_batch_item_done(self, idx, result):
        tasks = self.ai_batch_worker.tasks if hasattr(self.ai_batch_worker, 'tasks') else []
        if idx < len(tasks):
            seg_file, output_base = tasks[idx]
            title = result.get("title", "")
            cleaned_text = result.get("cleaned_text", "")

            ai_txt = os.path.join(AI_DIR, output_base + "_cleaned.txt")
            ai_json = os.path.join(AI_DIR, output_base + "_meta.json")

            video_path = self._find_video_path_by_output_base(output_base)
            meta = {
                "title": title,
                "video_path": video_path,
                "cleaned_file": ai_txt,
                "created_time": os.path.getctime(video_path) if video_path and os.path.exists(video_path) else 0,
                "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            with open(ai_txt, "w", encoding="utf-8") as f:
                f.write(cleaned_text)
            with open(ai_json, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            raw_txt = os.path.join(RAW_DIR, output_base + ".txt")
            try:
                with open(raw_txt, "w", encoding="utf-8") as f:
                    f.write(cleaned_text)
            except Exception:
                pass

            self._refresh_item_status_recursive_by_video(video_path)

    def _refresh_item_status_recursive_by_video(self, video_path):
        for item in self.top_items:
            if isinstance(item, VideoItem) and item.file_path == video_path:
                item.refresh_status()
        self._refresh_tree_item_by_video(video_path)

    def _find_video_path_by_output_base(self, output_base):
        for item in self.top_items:
            if isinstance(item, VideoItem):
                base = os.path.splitext(os.path.basename(item.file_path))[0]
                if base == output_base:
                    return item.file_path
        return None

    def on_ai_batch_all_done(self):
        self.ai_batch_btn.setEnabled(True)
        for item in self.top_items:
            if isinstance(item, VideoItem):
                item.refresh_status()
        self.refresh_tree()
        self.save_workspace()
        self.statusBar().showMessage("批量 AI 整理完成")

    def on_ai_batch_error(self, error_msg):
        self.ai_batch_btn.setEnabled(True)
        QMessageBox.critical(self, "错误", f"AI 整理失败：{error_msg}")

    # ---------- 打开知识库 ----------
    def open_knowledge_browser(self):
        self.kb_window = KnowledgeBrowserWindow(self, DEEPSEEK_API_KEY)
        self.kb_window.setAttribute(Qt.WA_DeleteOnClose)
        self.kb_window.show()

    # ---------- 右键菜单 ----------
    def show_context_menu(self, pos):
        menu = QMenu(self)
        remove_action = menu.addAction("移除选中项")
        preview_action = menu.addAction("预览")
        selected = self.tree_widget.selectedItems()
        if not selected:
            remove_action.setEnabled(False)
            preview_action.setEnabled(False)
        else:
            remove_action.setEnabled(True)
            preview_action.setEnabled(True)
        action = menu.exec(self.tree_widget.mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_items()
        elif action == preview_action:
            if selected:
                self.on_item_double_clicked(selected[0], 0)

    def remove_selected_items(self):
        selected = self.tree_widget.selectedItems()
        if not selected:
            return
        for item in selected:
            data = item.data(0, Qt.UserRole)
            if isinstance(data, VideoItem) and data in self.top_items:
                self.top_items.remove(data)
        self.refresh_tree()
        self.tree_widget.clearSelection()
        self.save_workspace()
        self.statusBar().showMessage("已移除选中项")

    # ---------- 自动备份 ----------
    def backup_data(self):
        """将当前树上的数据打包备份到 data/backups/"""
        backup_dir = BACKUP_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"backup_{timestamp}.zip")

        files_to_backup = []
        tree_file = os.path.join(BASE_DIR, "data", "knowledge_tree.json")
        if os.path.exists(tree_file):
            files_to_backup.append(tree_file)
        workspace_file = os.path.join(BASE_DIR, "data", "workspace.json")
        if os.path.exists(workspace_file):
            files_to_backup.append(workspace_file)

        root = load_tree()
        def collect_files(node):
            if node.is_content():
                if node.cleaned_file and os.path.exists(node.cleaned_file):
                    files_to_backup.append(node.cleaned_file)
                    meta_file = node.cleaned_file.replace("_cleaned.txt", "_meta.json")
                    if os.path.exists(meta_file):
                        files_to_backup.append(meta_file)
            for child in node.children:
                collect_files(child)
        collect_files(root)

        files_to_backup = list(set(files_to_backup))

        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in files_to_backup:
                    rel_path = os.path.relpath(f, os.path.join(BASE_DIR, "data"))
                    zf.write(f, arcname=rel_path)
            self.statusBar().showMessage(f"备份完成：{backup_path}", 5000)
            self._cleanup_old_backups(backup_dir, keep=10)
        except Exception as e:
            QMessageBox.warning(self, "备份失败", f"自动备份失败：{e}")

    def _cleanup_old_backups(self, backup_dir, keep=10):
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith("backup_") and f.endswith(".zip")])
        while len(backups) > keep:
            old_file = os.path.join(backup_dir, backups.pop(0))
            try:
                os.remove(old_file)
            except Exception:
                pass

    def closeEvent(self, event):
        self.backup_data()
        for thread_attr in ("worker_thread", "ai_batch_worker_thread"):
            thread = getattr(self, thread_attr, None)
            if thread is not None:
                try:
                    if thread.isRunning():
                        thread.quit()
                        thread.wait()
                except RuntimeError:
                    pass
        self.player.stop()
        self.player.setSource(QUrl())
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
