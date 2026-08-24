import os
import json
import shutil
import uuid
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QPlainTextEdit,
    QFrame, QSlider, QStyle, QGraphicsView,
    QGraphicsScene, QToolButton, QMenu, QWidgetAction, QMessageBox,
    QDialog, QDialogButtonBox, QTextEdit, QAbstractItemView, QSizePolicy,
    QLineEdit, QScrollArea, QInputDialog
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtCore import Qt, QUrl, QSize, Signal
from PySide6.QtGui import QFont, QColor, QBrush
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from knowledge_tree import load_tree, save_tree, TreeNode, is_video_mounted, remove_video_from_tree
from workspace import AI_DIR, RAW_DIR

BACKUP_DIR = os.path.join(os.path.dirname(AI_DIR), "merged_backup")
os.makedirs(BACKUP_DIR, exist_ok=True)


def format_time(seconds):
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"


def format_datetime(ts):
    """将时间戳格式化为 YYYY-MM-DD HH:MM"""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "未知时间"


class TitleLabel(QLabel):
    video_clicked = Signal(object)      # 传递 TreeNode
    edit_requested = Signal(object)     # 传递 TreeNode

    def __init__(self, node, parent=None):
        super().__init__(node.name if node else "", parent)
        self.node = node
        self.setCursor(Qt.PointingHandCursor if node and node.is_content() else Qt.ArrowCursor)
        self.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))

    def mouseDoubleClickEvent(self, event):
        if self.node:
            self.edit_requested.emit(self.node)
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.node and self.node.is_content():
            self.video_clicked.emit(self.node)
        super().mouseReleaseEvent(event)


class ContentLabel(QLabel):
    edit_requested = Signal(object)   # 传递 TreeNode

    def __init__(self, text, node, parent=None):
        super().__init__(text, parent)
        self.node = node
        self.setWordWrap(True)
        self.setFont(QFont("Microsoft YaHei", 9))

    def mouseDoubleClickEvent(self, event):
        if self.node:
            self.edit_requested.emit(self.node)
        super().mouseDoubleClickEvent(event)


class KnowledgeBrowserWindow(QMainWindow):
    def __init__(self, parent=None, api_key=""):
        super().__init__(parent)
        self.setWindowTitle("个人空间")
        screen = self.screen().availableGeometry()
        self.resize(int(screen.width() * 0.95), int(screen.height() * 0.9))
        self.move(screen.x() + (screen.width() - self.width()) // 2,
                  screen.y() + (screen.height() - self.height()) // 2)

        self.tree_root = load_tree()
        if self.tree_root.name != "个人空间":
            self.tree_root.name = "个人空间"
            save_tree(self.tree_root)

        self.current_video_path = None
        self.current_topic_node = None
        self.current_detail_topic = None
        self.is_collapsed = False
        self.playlist = []           # 当前播放列表
        self.playlist_index = 0      # 当前播放索引
        self.is_seeking = False      # 进度条拖动状态
        self.filter_unmounted = False  # 未挂载过滤状态

        self._build_ui()
        self.reload_tree()
        self.load_item_list()

    def _build_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 顶部按钮行
        top_btn_layout = QHBoxLayout()
        self.toggle_btn = QPushButton("一键折叠")
        self.toggle_btn.setFixedWidth(100)
        self.toggle_btn.clicked.connect(self.toggle_expand_collapse)
        top_btn_layout.addWidget(self.toggle_btn)
        top_btn_layout.addStretch(1)
        main_layout.addLayout(top_btn_layout)

        self.vertical_splitter = QSplitter(Qt.Vertical)
        self.horizontal_splitter = QSplitter(Qt.Horizontal)

        # 1. 左栏：知识树 (3/5)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setStyleSheet("QTreeWidget::branch { image: none; }")
        self.tree_widget.itemClicked.connect(self.on_tree_item_clicked)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.horizontal_splitter.addWidget(self.tree_widget)

        # 2. 中栏：总词条列表 (1/5)
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(4)

        self.filter_btn = QPushButton("未挂载")
        self.filter_btn.setCheckable(True)
        self.filter_btn.clicked.connect(self.toggle_filter_unmounted)
        middle_layout.addWidget(self.filter_btn)

        self.video_list = QListWidget()
        self.video_list.setWordWrap(True)
        self.video_list.setUniformItemSizes(True)
        self.video_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.video_list.itemClicked.connect(self.on_video_item_clicked)
        self.video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_list.customContextMenuRequested.connect(self.show_video_list_context_menu)
        middle_layout.addWidget(self.video_list)

        self.horizontal_splitter.addWidget(middle_widget)

        # 3. 右栏：视频播放器 (1/5)
        video_panel = QWidget()
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(5, 5, 5, 5)

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
        self.video_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player.setVideoOutput(self.video_item)
        video_layout.addWidget(self.video_view, stretch=1)

        controls_layout = QHBoxLayout()
        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setFixedWidth(30)
        self.play_pause_btn.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.play_pause_btn)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderPressed.connect(self.on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self.on_slider_released)
        self.progress_slider.sliderMoved.connect(self.seek)
        controls_layout.addWidget(self.progress_slider, 1)

        self.volume_btn = QToolButton()
        self.volume_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.volume_btn.setPopupMode(QToolButton.InstantPopup)
        volume_menu = QMenu(self)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self.set_volume)
        volume_action = QWidgetAction(volume_menu)
        volume_action.setDefaultWidget(self.volume_slider)
        volume_menu.addAction(volume_action)
        self.volume_btn.setMenu(volume_menu)
        controls_layout.addWidget(self.volume_btn)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFixedWidth(80)
        controls_layout.addWidget(self.time_label)

        self.rotate_btn = QPushButton("旋转")
        self.rotate_btn.setFixedWidth(40)
        self.rotate_btn.clicked.connect(self.rotate_video)
        controls_layout.addWidget(self.rotate_btn)

        video_layout.addLayout(controls_layout)
        self.horizontal_splitter.addWidget(video_panel)

        self.horizontal_splitter.setStretchFactor(0, 3)
        self.horizontal_splitter.setStretchFactor(1, 1)
        self.horizontal_splitter.setStretchFactor(2, 1)

        # 下部详情区
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(10, 10, 10, 10)
        self.detail_layout.setSpacing(12)
        self.detail_layout.setAlignment(Qt.AlignTop)
        self.detail_scroll.setWidget(self.detail_widget)

        self.vertical_splitter.addWidget(self.horizontal_splitter)
        self.vertical_splitter.addWidget(self.detail_scroll)
        total_height = self.height()
        self.vertical_splitter.setSizes([int(total_height * 2 / 3), int(total_height * 1 / 3)])

        main_layout.addWidget(self.vertical_splitter)
        self.setCentralWidget(central_widget)

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_state_changed)
        self.player.errorOccurred.connect(self.on_player_error)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.LoadedMedia:
            self.fit_video_to_view()
        elif status == QMediaPlayer.EndOfMedia:
            self._play_next_in_playlist()

    def _play_next_in_playlist(self):
        if self.playlist and self.playlist_index < len(self.playlist) - 1:
            self.playlist_index += 1
            self._load_video(self.playlist[self.playlist_index], autoplay=True)
        else:
            self.playlist = []
            self.playlist_index = 0
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def fit_video_to_view(self):
        if self.video_item.boundingRect().width() <= 0 or self.video_item.boundingRect().height() <= 0:
            return
        view_size = self.video_view.viewport().size()
        self.video_item.setSize(view_size)
        self.video_item.setPos(0, 0)
        self.video_scene.setSceneRect(0, 0, view_size.width(), view_size.height())
        self.video_view.setSceneRect(0, 0, view_size.width(), view_size.height())

    def reload_tree(self):
        self.tree_root = load_tree()
        if self.tree_root.name != "个人空间":
            self.tree_root.name = "个人空间"
            save_tree(self.tree_root)

        self.tree_widget.clear()
        root_item = QTreeWidgetItem(self.tree_widget)
        root_item.setText(0, self.tree_root.name)
        root_item.setData(0, Qt.UserRole, self.tree_root)
        self._populate_tree_item(root_item, self.tree_root)

        if self.is_collapsed:
            self._collapse_all_items()
        else:
            self._expand_all_items()

    def _populate_tree_item(self, ui_item, tree_node):
        for child in tree_node.children:
            child_item = QTreeWidgetItem(ui_item)
            child_item.setText(0, child.name)
            child_item.setData(0, Qt.UserRole, child)
            if child.is_topic():
                child_item.setForeground(0, QBrush(QColor("#2e8b57")))
                self._populate_tree_item(child_item, child)
            child_item.setExpanded(True)

    def _expand_all_items(self):
        root_item = self.tree_widget.topLevelItem(0)
        if root_item:
            def expand(item):
                item.setExpanded(True)
                for i in range(item.childCount()):
                    child = item.child(i)
                    expand(child)
            expand(root_item)
            root_item.setExpanded(True)

    def _collapse_all_items(self):
        root_item = self.tree_widget.topLevelItem(0)
        if root_item:
            def collapse(item):
                for i in range(item.childCount()):
                    child = item.child(i)
                    child.setExpanded(False)
                    collapse(child)
            collapse(root_item)
            root_item.setExpanded(True)

    def toggle_expand_collapse(self):
        if self.is_collapsed:
            self._expand_all_items()
            self.is_collapsed = False
            self.toggle_btn.setText("一键折叠")
        else:
            self._collapse_all_items()
            self.is_collapsed = True
            self.toggle_btn.setText("一键展开")

    def toggle_filter_unmounted(self):
        self.filter_unmounted = self.filter_btn.isChecked()
        self.load_item_list()

    def load_item_list(self):
        self.video_list.clear()
        mounted_videos = set()

        def collect_mounted(node):
            if node.is_content():
                if node.video:
                    mounted_videos.add(node.video)
                for v in node.video_list:
                    mounted_videos.add(v)
            for child in node.children:
                collect_mounted(child)
        collect_mounted(self.tree_root)

        videos = []
        for fname in os.listdir(AI_DIR):
            if fname.endswith("_meta.json"):
                path = os.path.join(AI_DIR, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("merged_into"):
                            continue
                        if isinstance(meta, dict) and "title" in meta:
                            video_path = meta.get("video_path", "")
                            video_list = meta.get("video_list", [])
                            videos.append({
                                "title": meta.get("title", ""),
                                "video_path": video_path,
                                "video_list": video_list,
                                "cleaned_file": meta.get("cleaned_file", ""),
                                "created_time": meta.get("created_time", 0),
                                "meta_file": path,
                                "is_merged": meta.get("is_merged", False),
                                "sources": meta.get("sources", [])
                            })
                except Exception:
                    continue

        videos.sort(key=lambda x: x.get("created_time", 0), reverse=True)

        for v in videos:
            all_videos = [v.get("video_path")] + v.get("video_list", [])
            mounted = any(vp and vp in mounted_videos for vp in all_videos)

            # 未挂载过滤
            if self.filter_unmounted and mounted:
                continue

            title = v.get("title", "未标题")
            created = format_datetime(v.get("created_time", 0))
            display = f"{title}\n{created}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, v)
            item.setSizeHint(QSize(0, 48))

            if mounted:
                font = QFont("Microsoft YaHei", 9)
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor(0, 0, 0))
            else:
                font = QFont("Microsoft YaHei", 9)
                item.setFont(font)
                item.setForeground(QColor(136, 136, 136))

            self.video_list.addItem(item)

    def show_video_list_context_menu(self, pos):
        selected_items = self.video_list.selectedItems()
        if not selected_items:
            return
        menu = QMenu(self)
        merge_action = None
        split_action = None
        delete_action = None
        location_action = None

        if len(selected_items) > 1:
            merge_action = menu.addAction("合并")
        elif len(selected_items) == 1:
            data = selected_items[0].data(Qt.UserRole)
            if data.get("is_merged"):
                split_action = menu.addAction("拆分")
                location_action = menu.addAction("查看视频位置")
            else:
                delete_action = menu.addAction("删除")
                location_action = menu.addAction("查看视频位置")

        action = menu.exec(self.video_list.viewport().mapToGlobal(pos))
        if action is None:
            return
        if merge_action and action == merge_action:
            self.merge_selected_videos()
        elif split_action and action == split_action:
            self.split_merged_video(selected_items[0])
        elif delete_action and action == delete_action:
            self.delete_video_item(selected_items[0])
        elif location_action and action == location_action:
            self.show_video_location(selected_items[0])

    def show_video_location(self, item):
        data = item.data(Qt.UserRole)
        dialog = QDialog(self)
        dialog.setWindowTitle("视频位置")
        dialog.resize(700, 400)
        layout = QVBoxLayout(dialog)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)
        content_layout.setAlignment(Qt.AlignTop)

        if data.get("is_merged"):
            # 合并节点：显示多个源视频
            sources = data.get("sources", [])
            for src in sources:
                if not os.path.exists(src):
                    continue
                try:
                    with open(src, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    title = meta.get("title", "未标题")
                    video_path = meta.get("video_path", "")
                    if video_path:
                        row = QHBoxLayout()
                        label_title = QLabel(title)
                        label_title.setFixedWidth(200)
                        btn_path = QPushButton(video_path)
                        btn_path.setFlat(True)
                        btn_path.setCursor(Qt.PointingHandCursor)  # 手型光标
                        btn_path.setStyleSheet("""
                            QPushButton {
                                text-align: left;
                                color: #0000ff;
                                text-decoration: underline;
                                border: none;
                                padding: 4px;
                            }
                            QPushButton:hover {
                                color: #ff0000;
                                text-decoration: underline;
                            }
                        """)
                        btn_path.setToolTip(video_path)  # 完整路径提示
                        btn_path.clicked.connect(lambda checked=False, p=video_path: self._open_file_location(p))
                        row.addWidget(label_title)
                        row.addWidget(btn_path, 1)
                        content_layout.addLayout(row)
                except Exception:
                    continue
        else:
            # 普通节点
            title = data.get("title", "未标题")
            video_path = data.get("video_path", "")
            if video_path:
                row = QHBoxLayout()
                label_title = QLabel(title)
                label_title.setFixedWidth(200)
                btn_path = QPushButton(video_path)
                btn_path.setFlat(True)
                btn_path.setCursor(Qt.PointingHandCursor)
                btn_path.setStyleSheet("""
                    QPushButton {
                        text-align: left;
                        color: #0000ff;
                        text-decoration: underline;
                        border: none;
                        padding: 4px;
                    }
                    QPushButton:hover {
                        color: #ff0000;
                        text-decoration: underline;
                    }
                """)
                btn_path.setToolTip(video_path)
                btn_path.clicked.connect(lambda checked=False, p=video_path: self._open_file_location(p))
                row.addWidget(label_title)
                row.addWidget(btn_path, 1)
                content_layout.addLayout(row)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, 0, Qt.AlignRight)

        dialog.exec()

    def _open_file_location(self, file_path):
        """打开资源管理器并选中文件（Windows）"""
        try:
            abs_path = os.path.abspath(file_path)
            subprocess.Popen(['explorer', '/select,', abs_path])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开文件位置：{e}")

    def merge_selected_videos(self):
        selected_items = self.video_list.selectedItems()
        if len(selected_items) < 2:
            return
        items_data = [item.data(Qt.UserRole) for item in selected_items]
        items_data.sort(key=lambda x: x.get("created_time", 0))

        titles = [d.get("title", "") for d in items_data]
        new_title = " ".join(titles).strip()

        contents = []
        for d in items_data:
            cleaned_file = d.get("cleaned_file", "")
            if cleaned_file and os.path.exists(cleaned_file):
                try:
                    with open(cleaned_file, "r", encoding="utf-8") as f:
                        contents.append(f.read())
                except Exception:
                    contents.append("")
            else:
                contents.append("")
        new_content = "\n\n".join(contents)

        new_meta_filename = f"merged_{uuid.uuid4().hex}_meta.json"
        new_cleaned_filename = f"merged_{uuid.uuid4().hex}_cleaned.txt"
        new_meta_path = os.path.join(AI_DIR, new_meta_filename)
        new_cleaned_path = os.path.join(AI_DIR, new_cleaned_filename)

        video_paths = []
        source_meta_paths = []
        for d in items_data:
            if d.get("video_path"):
                video_paths.append(d.get("video_path"))
            if d.get("video_list"):
                video_paths.extend(d.get("video_list"))
            if d.get("meta_file"):
                source_meta_paths.append(d.get("meta_file"))

        new_meta = {
            "title": new_title,
            "video_path": video_paths[0] if video_paths else None,
            "video_list": video_paths,
            "cleaned_file": new_cleaned_path,
            "created_time": items_data[0].get("created_time", 0),
            "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_merged": True,
            "sources": source_meta_paths
        }

        try:
            with open(new_cleaned_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            with open(new_meta_path, "w", encoding="utf-8") as f:
                json.dump(new_meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"合并失败：{e}")
            return

        # 标记源 meta 为 merged_into
        for meta_path in source_meta_paths:
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["merged_into"] = new_meta_path
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # 从树中移除源叶子（仅移除叶子，不删除主题）
        self._remove_content_node_only(video_paths)
        save_tree(self.tree_root)

        self.reload_tree()
        self.load_item_list()
        QMessageBox.information(self, "完成", "合并完成")

    def split_merged_video(self, item):
        data = item.data(Qt.UserRole)
        if not data.get("is_merged"):
            return
        sources = data.get("sources", [])
        if not sources:
            QMessageBox.warning(self, "错误", "找不到源数据，无法拆分")
            return

        # 从树中移除合并节点
        self._remove_merged_node_from_tree(data.get("video_list", []))

        # 恢复源 meta：清除 merged_into 标记
        for meta_path in sources:
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if "merged_into" in meta:
                    del meta["merged_into"]
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # 删除合并 meta 和 cleaned
        try:
            if data.get("meta_file") and os.path.exists(data["meta_file"]):
                os.remove(data["meta_file"])
            if data.get("cleaned_file") and os.path.exists(data["cleaned_file"]):
                os.remove(data["cleaned_file"])
        except Exception as e:
            QMessageBox.warning(self, "错误", f"删除合并文件失败：{e}")

        save_tree(self.tree_root)
        self.reload_tree()
        self.load_item_list()
        QMessageBox.information(self, "完成", "拆分完成")

    def delete_video_item(self, item):
        data = item.data(Qt.UserRole)
        ret = QMessageBox.question(self, "确认删除", "确定要删除该条目的所有处理数据吗？原始视频不会被删除。")
        if ret != QMessageBox.Yes:
            return

        files_to_delete = []
        if data.get("meta_file"):
            files_to_delete.append(data["meta_file"])
        if data.get("cleaned_file"):
            files_to_delete.append(data["cleaned_file"])

        # 如果是合并节点，删除合并数据并恢复源 meta
        if data.get("is_merged"):
            for meta_path in data.get("sources", []):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if "merged_into" in meta:
                        del meta["merged_into"]
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
        else:
            # 普通节点：删除 raw 文件
            for vp in [data.get("video_path")] + data.get("video_list", []):
                if vp:
                    base = os.path.splitext(os.path.basename(vp))[0]
                    files_to_delete.append(os.path.join(RAW_DIR, base + ".txt"))
                    files_to_delete.append(os.path.join(RAW_DIR, base + "_segments.json"))

        for f in files_to_delete:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        # 从树中移除相关节点
        for vp in [data.get("video_path")] + data.get("video_list", []):
            if vp:
                self.tree_root = remove_video_from_tree(self.tree_root, vp)
        save_tree(self.tree_root)

        self.reload_tree()
        self.load_item_list()
        self._clear_detail()
        QMessageBox.information(self, "完成", "已删除")

    def _remove_content_node_only(self, video_paths):
        """从树中移除指定视频路径的内容节点，不删除任何主题节点"""
        def remove_from_node(node):
            for child in list(node.children):
                if child.is_content():
                    if child.video in video_paths or any(vp in child.video_list for vp in video_paths):
                        node.children.remove(child)
                elif child.is_topic():
                    remove_from_node(child)
        remove_from_node(self.tree_root)

    def _remove_merged_node_from_tree(self, video_list):
        """从树中移除指定 video_list 的合并节点"""
        def find_and_remove(node):
            for child in list(node.children):
                if child.is_content() and child.video_list == video_list:
                    node.children.remove(child)
                    return True
                if child.is_topic():
                    if find_and_remove(child):
                        return True
            return False
        find_and_remove(self.tree_root)

    # ===== 以下为原有方法，保持不变 =====
    def show_tree_context_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return
        node = item.data(0, Qt.UserRole)
        if node is None:
            return
        menu = QMenu(self)
        if node.is_topic():
            new_topic_action = menu.addAction("新建主题")
            new_subtopic_action = menu.addAction("新建子主题")
            add_video_action = menu.addAction("添加视频到此主题")
            rename_action = menu.addAction("重命名")
            delete_action = menu.addAction("删除")
        else:
            rename_action = menu.addAction("重命名")
            delete_action = menu.addAction("删除")

        action = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
        if action == rename_action:
            self.rename_node(node)
        elif action == delete_action:
            self.delete_node(node)
        elif node.is_topic() and action == new_topic_action:
            self.create_topic(node, as_child=False)
        elif node.is_topic() and action == new_subtopic_action:
            self.create_topic(node, as_child=True)
        elif node.is_topic() and action == add_video_action:
            self.add_video_to_topic(node)

    def add_video_to_topic(self, topic_node):
        current_item = self.video_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先在总词条列表中选择一个视频")
            return
        data = current_item.data(Qt.UserRole)
        video_path = data.get("video_path")
        if is_video_mounted(self.tree_root, video_path):
            QMessageBox.information(self, "提示", "该视频已经挂载到树上")
            return
        title = data.get("title", "未标题")
        cleaned_file = data.get("cleaned_file", "")
        video_list = data.get("video_list", [])
        # 创建内容节点，保留 video_list 以支持连续播放
        content_node = TreeNode(title, video=video_path, cleaned_file=cleaned_file, video_list=video_list)
        topic_node.children.append(content_node)
        save_tree(self.tree_root)
        self.reload_tree()
        self.load_item_list()
        QMessageBox.information(self, "完成", "视频已添加")

    def create_topic(self, parent_node, as_child=False):
        name, ok = QInputDialog.getText(self, "新建主题", "请输入主题名称：")
        if not ok or not name.strip():
            return
        name = name.strip()
        new_node = TreeNode(name)
        if as_child:
            parent_node.children.append(new_node)
        else:
            parent_parent = self._find_parent_node(self.tree_root, parent_node)
            if parent_parent is None:
                self.tree_root.children.append(new_node)
            else:
                idx = parent_parent.children.index(parent_node)
                parent_parent.children.insert(idx + 1, new_node)
        save_tree(self.tree_root)
        self.reload_tree()
        self.load_item_list()

    def rename_node(self, node):
        name, ok = QInputDialog.getText(self, "重命名", "请输入新名称：", text=node.name)
        if not ok or not name.strip():
            return
        new_name = name.strip()
        node.name = new_name
        if node.is_content() and node.video:
            self._update_meta_title(node.video, new_name)
        save_tree(self.tree_root)
        self.reload_tree()
        self.load_item_list()
        if self.current_detail_topic:
            self._show_topic_detail(self.current_detail_topic)
        elif self.current_video_path:
            node = self._find_content_node_by_video(self.tree_root, self.current_video_path)
            if node:
                self._show_content_detail(node)

    def delete_node(self, node):
        if node.is_topic() and node.children:
            ret = QMessageBox.question(self, "删除确认", "该主题下有子节点，删除后子内容将变为未挂载，是否继续？")
            if ret != QMessageBox.Yes:
                return
        parent = self._find_parent_node(self.tree_root, node)
        if parent is None:
            if node == self.tree_root:
                QMessageBox.warning(self, "警告", "不能删除根节点")
                return
            else:
                self.tree_root.children.remove(node)
        else:
            parent.children.remove(node)
        save_tree(self.tree_root)
        self.reload_tree()
        self.load_item_list()
        self._clear_detail()

    def _find_parent_node(self, root, target):
        for child in root.children:
            if child == target:
                return root
            found = self._find_parent_node(child, target)
            if found:
                return found
        return None

    def _update_meta_title(self, video_path, new_title):
        for fname in os.listdir(AI_DIR):
            if fname.endswith("_meta.json"):
                path = os.path.join(AI_DIR, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if isinstance(meta, dict) and meta.get("video_path") == video_path:
                        meta["title"] = new_title
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, ensure_ascii=False, indent=2)
                        return
                except Exception:
                    continue

    def on_tree_item_clicked(self, item, column):
        node = item.data(0, Qt.UserRole)
        if node is None:
            return
        if node.is_content():
            self._show_content_detail(node)
            if node.video_list:
                self.playlist = node.video_list
                self.playlist_index = 0
                self._load_video(self.playlist[0], autoplay=False)
            else:
                self.playlist = []
                self._load_video(node.video, autoplay=False)
            self._select_video_in_list(node.video if node.video else node.video_list[0] if node.video_list else "")
        else:
            self._show_topic_detail(node)
            self.player.stop()
            self.player.setSource(QUrl())

    def on_video_item_clicked(self, item):
        data = item.data(Qt.UserRole)
        if data:
            video_path = data.get("video_path")
            video_list = data.get("video_list", [])
            self._select_tree_node_by_video(video_path)
            node = self._find_content_node_by_video(self.tree_root, video_path)
            if node:
                self._show_content_detail(node)
                if node.video_list:
                    self.playlist = node.video_list
                elif video_list:
                    self.playlist = video_list
                else:
                    self.playlist = []
                self.playlist_index = 0
                self._load_video(self.playlist[0] if self.playlist else video_path, autoplay=False)
            else:
                if video_list:
                    self.playlist = video_list
                else:
                    self.playlist = []
                self.playlist_index = 0
                self._load_video(self.playlist[0] if self.playlist else video_path, autoplay=False)
                self._show_unmounted_detail(data)

    def _select_tree_node_by_video(self, video_path):
        def traverse(item):
            for i in range(item.childCount()):
                child = item.child(i)
                node = child.data(0, Qt.UserRole)
                if node and node.is_content():
                    if node.video == video_path or video_path in node.video_list:
                        self.tree_widget.setCurrentItem(child)
                        self.tree_widget.scrollToItem(child)
                        return True
                if child.childCount() > 0 and traverse(child):
                    return True
            return False
        root = self.tree_widget.topLevelItem(0)
        if root:
            traverse(root)

    def _find_content_node_by_video(self, root, video_path):
        if root.is_content():
            if root.video == video_path or video_path in root.video_list:
                return root
        for child in root.children:
            found = self._find_content_node_by_video(child, video_path)
            if found:
                return found
        return None

    def _select_video_in_list(self, video_path):
        for i in range(self.video_list.count()):
            item = self.video_list.item(i)
            data = item.data(Qt.UserRole)
            if data and (data.get("video_path") == video_path or video_path in data.get("video_list", [])):
                self.video_list.setCurrentItem(item)
                self.video_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                break

    def _show_content_detail(self, node):
        self._clear_detail()
        self.current_video_path = node.video if node.video else node.video_list[0] if node.video_list else None
        self.current_topic_node = None
        self.current_detail_topic = None
        card = self._create_card(node, indent=0)
        self.detail_layout.addWidget(card)

    def _show_unmounted_detail(self, data):
        self._clear_detail()
        self.current_video_path = data.get("video_path")
        self.current_topic_node = None
        self.current_detail_topic = None
        temp_node = TreeNode(
            data.get("title", ""),
            video=data.get("video_path", ""),
            cleaned_file=data.get("cleaned_file", ""),
            video_list=data.get("video_list", [])
        )
        card = self._create_card(temp_node, indent=0)
        self.detail_layout.addWidget(card)

    def _show_topic_detail(self, node):
        self._clear_detail()
        self.current_topic_node = node
        self.current_video_path = None
        self.current_detail_topic = node
        self._add_node_cards_recursive(node, indent=0)

    def _add_node_cards_recursive(self, node, indent):
        card = self._create_card(node, indent=indent)
        self.detail_layout.addWidget(card)
        for child in node.children:
            if child.is_topic():
                self._add_node_cards_recursive(child, indent + 1)
            else:
                leaf_card = self._create_card(child, indent=indent + 1)
                self.detail_layout.addWidget(leaf_card)

    def _create_card(self, node, indent=0):
        card = QFrame()
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(indent * 20, 4, 10, 4)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_label = TitleLabel(node, parent=self)
        title_label.video_clicked.connect(self._on_card_title_clicked)
        title_label.edit_requested.connect(self._on_title_edit_requested)
        title_row.addWidget(title_label)
        title_row.addStretch(1)

        if node.is_content():
            video_for_time = node.video if node.video else node.video_list[0] if node.video_list else None
            if video_for_time and os.path.exists(video_for_time):
                ct = os.path.getctime(video_for_time)
                time_str = format_datetime(ct)
                time_label = QLabel(time_str)
                title_row.addWidget(time_label)

        layout.addLayout(title_row)

        if node.is_content() and node.cleaned_file and os.path.exists(node.cleaned_file):
            try:
                with open(node.cleaned_file, "r", encoding="utf-8") as f:
                    content = f.read()
                content_label = ContentLabel(content, node, parent=self)
                content_label.edit_requested.connect(self._on_content_edit_requested)
                layout.addWidget(content_label)
            except Exception:
                pass

        return card

    def _on_card_title_clicked(self, node):
        if node and node.is_content():
            if node.video_list:
                self.playlist = node.video_list
                self.playlist_index = 0
                self._load_video(self.playlist[0], autoplay=False)
                self._select_video_in_list(self.playlist[0])
            elif node.video:
                self.playlist = []
                self._load_video(node.video, autoplay=False)
                self._select_video_in_list(node.video)

    def _on_title_edit_requested(self, node):
        if node:
            self.rename_node(node)

    def _on_content_edit_requested(self, node):
        if node and node.cleaned_file:
            self._edit_content_dialog(node.cleaned_file)

    def _edit_content_dialog(self, cleaned_file):
        try:
            with open(cleaned_file, "r", encoding="utf-8") as f:
                current_text = f.read()
        except Exception:
            current_text = ""

        dialog = QDialog(self)
        dialog.setWindowTitle("编辑原文")
        dialog.resize(700, 500)
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setPlainText(current_text)
        layout.addWidget(text_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            new_text = text_edit.toPlainText()
            try:
                with open(cleaned_file, "w", encoding="utf-8") as f:
                    f.write(new_text)
                if self.current_detail_topic:
                    self._show_topic_detail(self.current_detail_topic)
                elif self.current_video_path:
                    node = self._find_content_node_by_video(self.tree_root, self.current_video_path)
                    if node:
                        self._show_content_detail(node)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"保存失败：{e}")

    def _clear_detail(self):
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _load_video(self, video_path, autoplay=False):
        if video_path and os.path.exists(video_path):
            url = QUrl.fromLocalFile(video_path)
            self.player.setSource(url)
            if autoplay:
                self.player.play()
            else:
                self.player.pause()
        else:
            self.player.stop()
            self.player.setSource(QUrl())

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, pos):
        self.player.setPosition(pos)

    def on_slider_pressed(self):
        self.is_seeking = True

    def on_slider_released(self):
        self.is_seeking = False
        pos = self.progress_slider.value()
        self.player.setPosition(pos)

    def set_volume(self, val):
        self.audio_output.setVolume(val / 100.0)

    def rotate_video(self):
        angle = (self.video_item.rotation() + 90) % 360
        self.video_item.setRotation(angle)
        self.video_item.setTransformOriginPoint(self.video_item.boundingRect().center())
        self.fit_video_to_view()

    def on_position_changed(self, pos):
        if not self.is_seeking:
            self.progress_slider.setValue(pos)
        dur = self.player.duration()
        if dur > 0:
            self.time_label.setText(f"{format_time(pos/1000)} / {format_time(dur/1000)}")
        else:
            self.time_label.setText(f"{format_time(pos/1000)} / 00:00")

    def on_duration_changed(self, dur):
        self.progress_slider.setRange(0, dur)
        self.time_label.setText(f"00:00 / {format_time(dur/1000)}")

    def on_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def on_player_error(self, error, error_string):
        QMessageBox.warning(self, "播放错误", f"视频播放失败：{error_string}")