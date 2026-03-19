from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from app.widgets.progress_card import ProgressCard
from app.services.upload_worker import PrepWorker, UploadWorker
from app.config import PREP_DIR, get_index_id
from app.services.api_client import get_client
from app import video_map


class UploadPanel(QWidget):
    upload_complete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, ProgressCard] = {}
        self._prep_worker: PrepWorker | None = None
        self._upload_worker: UploadWorker | None = None
        self._prepared_files: dict[str, list[str]] = {}  # original -> prepared paths
        self._upload_to_card: dict[str, str] = {}  # prepared path -> original path
        self._pending_uploads: list[str] = []  # prepared paths waiting to upload
        self._prep_finished = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("Upload Queue")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.addStretch()
        scroll.setWidget(self.card_container)
        layout.addWidget(scroll)

    def start_upload(self, file_paths: list[str]):
        """Begin preprocessing then uploading the given files."""
        self._prepared_files.clear()

        # Check for duplicates
        new_paths = []
        duplicates = []
        for path_str in file_paths:
            existing_id = video_map.find_by_path(path_str)
            if existing_id:
                duplicates.append((path_str, existing_id))
            else:
                new_paths.append(path_str)

        if duplicates:
            names = "\n".join(
                f"  - {Path(p).name}  (ID: {vid[:12]}...)"
                for p, vid in duplicates
            )
            msg = (
                f"{len(duplicates)} file(s) already uploaded:\n{names}\n\n"
                f"Re-upload them anyway?"
            )
            reply = QMessageBox.question(
                self, "Duplicate Videos", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                file_paths = new_paths

        if not file_paths:
            return

        # Resolve current index name for display
        index_name = ""
        try:
            index_id = get_index_id()
            if index_id:
                client = get_client()
                idx = client.indexes.retrieve(index_id)
                index_name = idx.index_name or index_id[:12]
        except Exception:
            index_name = get_index_id() or ""
            if len(index_name) > 12:
                index_name = index_name[:12] + "..."

        for path_str in file_paths:
            filename = Path(path_str).name
            label = f"{filename} → {index_name}" if index_name else filename
            card = ProgressCard(label)
            self._cards[path_str] = card
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)

        # Start preprocessing — uploads begin as each file is ready
        self._pending_uploads.clear()
        self._prep_finished = False
        self._prep_worker = PrepWorker(file_paths, self)
        self._prep_worker.prep_progress.connect(self._on_prep_progress)
        self._prep_worker.prep_done.connect(self._on_prep_done)
        self._prep_worker.error.connect(self._on_prep_error)
        self._prep_worker.finished.connect(self._on_all_prepped)
        self._prep_worker.start()

    def _on_prep_progress(self, path: str, status: str, percent: int):
        if path in self._cards:
            self._cards[path].update_status(status, percent)

    def _on_prep_done(self, original_path: str, prepared_paths: list[str]):
        self._prepared_files[original_path] = prepared_paths
        for p in prepared_paths:
            self._upload_to_card[p] = original_path
            self._pending_uploads.append(p)
        self._flush_uploads()

    def _on_prep_error(self, path: str, msg: str):
        if path in self._cards:
            self._cards[path].mark_error(msg)

    def _on_all_prepped(self):
        self._prep_finished = True
        # If no uploads were started (e.g. all files failed prep), nothing to do
        if not self._upload_worker and not self._pending_uploads:
            return
        self._flush_uploads()

    def _flush_uploads(self):
        """Feed pending prepared files to the upload worker."""
        if not self._pending_uploads:
            return

        batch = self._pending_uploads.copy()
        self._pending_uploads.clear()

        if self._upload_worker is None:
            self._upload_worker = UploadWorker(batch, self)
            self._upload_worker.progress.connect(self._on_upload_progress)
            self._upload_worker.finished.connect(self._on_upload_finished)
            self._upload_worker.error.connect(self._on_upload_error)
            self._upload_worker.all_done.connect(self._on_upload_batch_done)
            self._upload_worker.start()
        else:
            # Previous batch still running — queue a new worker once it finishes
            self._pending_uploads.extend(batch)

    def _on_upload_batch_done(self):
        """Called when an upload worker finishes its batch."""
        self._upload_worker = None
        if self._pending_uploads:
            self._flush_uploads()
        elif self._prep_finished:
            self._on_all_uploaded()

    def _on_upload_progress(self, path: str, status: str, percent: int):
        original = self._upload_to_card.get(path, path)
        if original in self._cards:
            self._cards[original].update_status(status, percent)

    def _on_upload_finished(self, path: str, video_id: str):
        original = self._upload_to_card.get(path, path)
        if original in self._cards:
            self._cards[original].mark_done()
        # Save video_id -> original local path for gallery thumbnails/playback
        if video_id and original:
            video_map.set_path(video_id, original)
        # Remove the prep file now that it's uploaded
        self._cleanup_prep_file(path)

    def _on_upload_error(self, path: str, msg: str):
        original = self._upload_to_card.get(path, path)
        if original in self._cards:
            self._cards[original].mark_error(msg)
        self._cleanup_prep_file(path)

    def _cleanup_prep_file(self, path: str):
        """Delete a single prep file if it lives in .prep/."""
        p = Path(path)
        if p.exists() and PREP_DIR in p.parents:
            p.unlink(missing_ok=True)

    def _on_all_uploaded(self):
        # Remove .prep directory if empty
        if PREP_DIR.exists() and not any(PREP_DIR.iterdir()):
            PREP_DIR.rmdir()
        self.upload_complete.emit()
