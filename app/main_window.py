from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from app.config import get_api_key, get_index_id, set_index_id
from app.services.api_client import get_client
from app.views.folder_browser import FolderBrowser
from app.views.upload_panel import UploadPanel
from app.views.gallery_view import GalleryView
from app.views.video_detail import VideoDetailView
from app.views.search_view import SearchView
from app.views.highlights_view import HighlightsView
from app.views.settings_dialog import SettingsDialog
from app import video_map


_CREATE_NEW_SENTINEL = "__create_new__"


class _LoadIndexesWorker(QThread):
    result = Signal(list)

    def run(self):
        try:
            client = get_client()
            indexes = client.indexes.list(page=1, page_limit=50)
            self.result.emit([
                {"id": idx.id, "name": idx.index_name or idx.id}
                for idx in indexes
            ])
        except Exception:
            self.result.emit([])


class _CreateIndexWorker(QThread):
    result = Signal(str, str)  # id, name
    error = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.index_name = name

    def run(self):
        try:
            from twelvelabs.indexes import IndexesCreateRequestModelsItem
            client = get_client()
            index = client.indexes.create(
                index_name=self.index_name,
                models=[
                    IndexesCreateRequestModelsItem(
                        model_name="marengo3.0",
                        model_options=["visual", "audio"],
                    ),
                    IndexesCreateRequestModelsItem(
                        model_name="pegasus1.2",
                        model_options=["visual", "audio"],
                    ),
                ],
            )
            self.result.emit(index.id, self.index_name)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twelve Labs Video Highlights")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self._setup_ui()
        self._load_stylesheet()

        self._workers: list = []
        self._index_loading = False

        # Show settings on first launch
        if not get_api_key() or not get_index_id():
            self._show_settings(force=True)

        self._refresh_indexes()

    def _load_stylesheet(self):
        qss_path = Path(__file__).parent / "style.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text())

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 12)
        sidebar_layout.setSpacing(0)

        self.nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("upload", "Upload"),
            ("gallery", "Gallery"),
            ("search", "Search"),
            ("highlights", "Highlights"),
            ("settings", "Settings"),
        ]

        for key, label in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, k=key: self._navigate(k))
            sidebar_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        sidebar_layout.addStretch()
        main_layout.addWidget(sidebar)

        # Right side: header bar + content stack
        right_side = QVBoxLayout()
        right_side.setContentsMargins(0, 0, 0, 0)
        right_side.setSpacing(0)

        # Index selector header bar
        header_bar = QWidget()
        header_bar.setObjectName("indexBar")
        header_bar.setFixedHeight(40)
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(12, 4, 12, 4)
        header_layout.addStretch()
        header_layout.addWidget(QLabel("Index:"))
        self.index_combo = QComboBox()
        self.index_combo.setFixedWidth(220)
        self.index_combo.currentIndexChanged.connect(self._on_index_changed)
        header_layout.addWidget(self.index_combo)
        right_side.addWidget(header_bar)

        # Content area
        self.stack = QStackedWidget()
        right_side.addWidget(self.stack, stretch=1)
        main_layout.addLayout(right_side, stretch=1)

        # Upload view (folder browser + upload panel)
        upload_view = QWidget()
        upload_layout = QVBoxLayout(upload_view)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.folder_browser = FolderBrowser()
        self.upload_panel = UploadPanel()
        self.folder_browser.upload_requested.connect(self.upload_panel.start_upload)
        self.upload_panel.upload_complete.connect(self._on_upload_complete)
        splitter.addWidget(self.folder_browser)
        splitter.addWidget(self.upload_panel)
        splitter.setSizes([400, 200])
        upload_layout.addWidget(splitter)
        self.stack.addWidget(upload_view)  # index 0

        # Gallery view
        self.gallery_view = GalleryView()
        self.gallery_view.video_selected.connect(self._open_video_detail)
        self.stack.addWidget(self.gallery_view)  # index 1

        # Search view
        self.search_view = SearchView()
        self.search_view.result_clicked.connect(self._on_search_result_clicked)
        self.stack.addWidget(self.search_view)  # index 2

        # Highlights view
        self.highlights_view = HighlightsView()
        self.highlights_view.result_clicked.connect(self._on_search_result_clicked)
        self.stack.addWidget(self.highlights_view)  # index 3

        # Video detail view
        self.video_detail = VideoDetailView()
        self.video_detail.back_requested.connect(self._go_back_from_detail)
        self.stack.addWidget(self.video_detail)  # index 4

        # Default to upload
        self._navigate("upload")

    def _refresh_indexes(self):
        """Load available indexes into the combo box."""
        if not get_api_key():
            return
        self._index_loading = True
        worker = _LoadIndexesWorker(self)
        worker.result.connect(self._on_indexes_loaded)
        self._workers.append(worker)
        worker.start()

    def _on_indexes_loaded(self, indexes: list):
        self._index_loading = True
        self.index_combo.clear()
        current_id = get_index_id()
        select_idx = 0
        for i, idx in enumerate(indexes):
            self.index_combo.addItem(
                f"{idx['name']} ({idx['id'][:8]}...)", idx["id"],
            )
            if idx["id"] == current_id:
                select_idx = i
        self.index_combo.addItem("+ Create New Index", _CREATE_NEW_SENTINEL)
        if indexes:
            self.index_combo.setCurrentIndex(select_idx)
        self._index_loading = False

    def _on_index_changed(self, idx: int):
        if self._index_loading or idx < 0:
            return
        index_id = self.index_combo.currentData()
        if index_id == _CREATE_NEW_SENTINEL:
            self._create_new_index()
            return
        if index_id and index_id != get_index_id():
            set_index_id(index_id)
            self.gallery_view.refresh()
            self.highlights_view._refresh_scope()

    def _create_new_index(self):
        # Revert combo to previous index while dialog is open
        self._index_loading = True
        current_id = get_index_id()
        for i in range(self.index_combo.count()):
            if self.index_combo.itemData(i) == current_id:
                self.index_combo.setCurrentIndex(i)
                break
        self._index_loading = False

        name, ok = QInputDialog.getText(self, "Create New Index", "Index name:")
        if not ok or not name.strip():
            return
        self.index_combo.setEnabled(False)
        worker = _CreateIndexWorker(name.strip(), self)
        worker.result.connect(self._on_index_created)
        worker.error.connect(self._on_create_index_error)
        self._workers.append(worker)
        worker.start()

    def _on_index_created(self, index_id: str, name: str):
        self.index_combo.setEnabled(True)
        set_index_id(index_id)
        self._refresh_indexes()

    def _on_create_index_error(self, msg: str):
        self.index_combo.setEnabled(True)
        QMessageBox.warning(self, "Error", f"Failed to create index:\n{msg}")

    def _navigate(self, key: str):
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)

        if key == "upload":
            self.stack.setCurrentIndex(0)
        elif key == "gallery":
            self.stack.setCurrentIndex(1)
            self.gallery_view.refresh()
        elif key == "search":
            self.stack.setCurrentIndex(2)
        elif key == "highlights":
            self.stack.setCurrentIndex(3)
            self.highlights_view._refresh_scope()
        elif key == "settings":
            self._show_settings()
            # Stay on current page after settings
            return

        self._last_nav = key

    def _show_settings(self, force=False):
        dialog = SettingsDialog(self, force_modal=force)
        dialog.exec()
        self._refresh_indexes()

    def _open_video_detail(self, video_id: str, name: str = "",
                           duration: float = 0, created_at: str = "",
                           local_path: str = "",
                           seek_to: float = 0, clip_start: float = 0,
                           clip_end: float = 0):
        self.video_detail.load_video(
            video_id, name, duration, created_at, local_path,
            seek_to, clip_start, clip_end,
        )
        self._pre_detail_index = self.stack.currentIndex()
        self.stack.setCurrentIndex(4)

    def _on_search_result_clicked(self, video_id: str, start: float, end: float):
        local_path = video_map.get_path(video_id) or ""
        name = Path(local_path).name if local_path else video_id
        self._open_video_detail(
            video_id, name, 0, "", local_path,
            seek_to=start, clip_start=start, clip_end=end,
        )

    def _go_back_from_detail(self):
        idx = getattr(self, "_pre_detail_index", 1)
        self.stack.setCurrentIndex(idx)

    def _on_upload_complete(self):
        pass  # Could auto-switch to gallery
