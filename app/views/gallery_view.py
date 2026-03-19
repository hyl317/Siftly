from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.services.api_client import get_client
from app.config import get_index_id, PROJECT_ROOT
from app.widgets.video_thumbnail import VideoThumbnail
from app import video_map
from app.utils.thumbnails import extract_thumbnail

THUMB_DIR = PROJECT_ROOT / ".thumbnails"


class _FetchVideosWorker(QThread):
    result = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            client = get_client()
            index_id = get_index_id()
            if not index_id:
                self.result.emit([])
                return
            videos = client.indexes.videos.list(index_id=index_id, page=1, page_limit=50)
            path_map = video_map.get_all()
            items = []
            for v in videos:
                meta = v.system_metadata
                vid = v.id or ""
                local_path = path_map.get(vid, "")
                file_exists = bool(local_path and Path(local_path).exists())

                # Generate thumbnail if we have a local file
                thumb_path = ""
                if local_path:
                    tp = THUMB_DIR / f"{vid}.jpg"
                    if tp.exists():
                        thumb_path = str(tp)
                    elif file_exists:
                        if extract_thumbnail(Path(local_path), tp):
                            thumb_path = str(tp)

                items.append({
                    "video_id": vid,
                    "name": (meta.filename if meta and meta.filename else vid) or vid,
                    "duration": (meta.duration if meta else 0) or 0,
                    "created_at": str(v.created_at or ""),
                    "local_path": local_path,
                    "file_exists": file_exists,
                    "thumbnail": thumb_path,
                })
            self.result.emit(items)
        except Exception as e:
            self.error.emit(str(e))


class _DeleteVideoWorker(QThread):
    done = Signal(str)  # video_id
    error = Signal(str, str)  # video_id, message

    def __init__(self, video_id: str, parent=None):
        super().__init__(parent)
        self.video_id = video_id

    def run(self):
        try:
            client = get_client()
            index_id = get_index_id()
            client.indexes.videos.delete(index_id=index_id, video_id=self.video_id)
            self.done.emit(self.video_id)
        except Exception as e:
            self.error.emit(self.video_id, str(e))


class GalleryView(QWidget):
    video_selected = Signal(str, str, float, str, str)  # video_id, name, duration, created_at, local_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Gallery")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        header.addWidget(title)
        header.addWidget(self.status_label, stretch=1)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.grid_container)
        layout.addWidget(scroll)

    def refresh(self):
        self.status_label.setText("Loading...")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        self.refresh_btn.setEnabled(False)
        worker = _FetchVideosWorker(self)
        worker.result.connect(self._on_videos)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def _on_videos(self, videos: list):
        self.refresh_btn.setEnabled(True)
        self._clear_grid()

        if not videos:
            self.status_label.setText("No videos indexed yet")
            return

        self.status_label.setText(f"{len(videos)} videos")

        # Lay out in rows of 4
        row_layout = None
        for i, v in enumerate(videos):
            if i % 4 == 0:
                row_layout = QHBoxLayout()
                row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                self.grid_layout.addLayout(row_layout)

            thumb_path = v.get("thumbnail") or None
            has_local = bool(v.get("local_path"))
            file_missing = has_local and not v.get("file_exists", True)

            thumb = VideoThumbnail(
                identifier=v["video_id"],
                name=v.get("name", v["video_id"]),
                thumbnail_path=Path(thumb_path) if thumb_path else None,
                file_missing=file_missing,
                duration=v.get("duration", 0),
            )
            thumb.clicked.connect(
                lambda vid=v["video_id"], n=v.get("name", ""), d=v.get("duration", 0),
                       c=v.get("created_at", ""), lp=v.get("local_path", ""):
                self.video_selected.emit(vid, n, d, c, lp)
            )
            thumb.reveal_requested.connect(self._reveal_in_finder)
            thumb.delete_requested.connect(self._confirm_delete)
            row_layout.addWidget(thumb)

    def _reveal_in_finder(self, video_id: str):
        local_path = video_map.get_path(video_id)
        if not local_path or not Path(local_path).exists():
            QMessageBox.information(
                self, "File Not Found",
                "No local file is associated with this video.",
            )
            return
        import subprocess
        subprocess.Popen(["open", "-R", local_path])

    def _confirm_delete(self, video_id: str):
        reply = QMessageBox.question(
            self, "Delete Video",
            f"Delete video {video_id[:12]}... from the index?\n\n"
            "This removes it from Twelve Labs. Local files are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.status_label.setText("Deleting...")
            worker = _DeleteVideoWorker(video_id, self)
            worker.done.connect(self._on_deleted)
            worker.error.connect(self._on_delete_error)
            self._workers.append(worker)
            worker.start()

    def _on_deleted(self, video_id: str):
        self.status_label.setText(f"Deleted {video_id[:12]}...")
        self.refresh()

    def _on_delete_error(self, video_id: str, msg: str):
        self.status_label.setText(f"Delete failed: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def _on_error(self, msg: str):
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")
