from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.utils.file_scanner import scan_folder
from app.utils.thumbnails import probe_video
from app.config import MAX_RESOLUTION_HEIGHT, MAX_FILE_SIZE_BYTES, VIDEO_EXTENSIONS


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


class FolderBrowser(QWidget):
    upload_requested = Signal(list)  # list of file path strings

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_items: dict[str, QTreeWidgetItem] = {}
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setStyleSheet("font-size: 13px; color: #888;")
        self.select_btn = QPushButton("Select Folder")
        self.select_btn.clicked.connect(self._select_folder)
        header.addWidget(self.folder_label, stretch=1)
        header.addWidget(self.select_btn)
        layout.addLayout(header)

        # Check all / Upload
        action_row = QHBoxLayout()
        self.check_all = QCheckBox("Select All")
        self.check_all.stateChanged.connect(self._toggle_all)
        self.upload_btn = QPushButton("Upload Selected")
        self.upload_btn.clicked.connect(self._upload_selected)
        self.upload_btn.setEnabled(False)
        action_row.addWidget(self.check_all)
        action_row.addStretch()
        action_row.addWidget(self.upload_btn)
        layout.addLayout(action_row)

        # File list with drop hint overlay
        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()

        # Page 0: drop hint
        self._drop_hint = QLabel("Drop video files here\nor use Select Folder above")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet(
            "color: #4a5568; font-size: 14px; border: 2px dashed #2a3f5f; border-radius: 8px;"
        )
        self._stack.addWidget(self._drop_hint)

        # Page 1: file tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Filename", "Size", "Duration", "Resolution", "Notes"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        header_view = self.tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 100)
        self.tree.setColumnWidth(5, 160)
        self._stack.addWidget(self.tree)

        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder")
        if not folder:
            return
        self.folder_label.setText(folder)
        self._scan(Path(folder))

    def _scan(self, folder: Path):
        self.tree.clear()
        self._video_items.clear()
        videos = scan_folder(folder)

        for vpath in videos:
            info = probe_video(vpath)
            size = vpath.stat().st_size
            res_str = f"{info['width']}x{info['height']}" if info["width"] else "?"

            notes = []
            if info["height"] > MAX_RESOLUTION_HEIGHT:
                notes.append(f"→ 720p")
            if size > MAX_FILE_SIZE_BYTES:
                notes.append("→ will split")

            item = QTreeWidgetItem()
            item.setCheckState(0, Qt.CheckState.Unchecked)
            duration = info.get("duration", 0)
            m, s = divmod(int(duration), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            item.setText(1, vpath.name)
            item.setText(2, _human_size(size))
            item.setText(3, dur_str)
            item.setText(4, res_str)
            item.setText(5, ", ".join(notes))
            item.setData(0, Qt.ItemDataRole.UserRole, str(vpath))
            self.tree.addTopLevelItem(item)
            self._video_items[str(vpath)] = item

        self.upload_btn.setEnabled(len(videos) > 0)
        self._stack.setCurrentIndex(1 if videos else 0)

    def _toggle_all(self, state):
        check = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, check)

    def _upload_selected(self):
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                selected.append(item.data(0, Qt.ItemDataRole.UserRole))
        if selected:
            self.upload_requested.emit(selected)

    # ── Drag and drop ──────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                paths.append(p)
            elif p.is_dir():
                paths.extend(scan_folder(p))
        if not paths:
            return
        event.acceptProposedAction()
        self._add_files(paths)

    def _add_files(self, paths: list[Path]):
        """Add individual video files to the tree, skipping duplicates."""
        for vpath in sorted(paths):
            if str(vpath) in self._video_items:
                continue
            info = probe_video(vpath)
            size = vpath.stat().st_size
            res_str = f"{info['width']}x{info['height']}" if info["width"] else "?"

            notes = []
            if info["height"] > MAX_RESOLUTION_HEIGHT:
                notes.append("→ 720p")
            if size > MAX_FILE_SIZE_BYTES:
                notes.append("→ will split")

            duration = info.get("duration", 0)
            m, s = divmod(int(duration), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            item = QTreeWidgetItem()
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setText(1, vpath.name)
            item.setText(2, _human_size(size))
            item.setText(3, dur_str)
            item.setText(4, res_str)
            item.setText(5, ", ".join(notes))
            item.setData(0, Qt.ItemDataRole.UserRole, str(vpath))
            self.tree.addTopLevelItem(item)
            self._video_items[str(vpath)] = item

        self.upload_btn.setEnabled(self.tree.topLevelItemCount() > 0)
        self._stack.setCurrentIndex(1 if self.tree.topLevelItemCount() else 0)
        self.folder_label.setText(f"{self.tree.topLevelItemCount()} videos")
