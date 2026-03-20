"""Dialogs for DaVinci Resolve integration (create project / append to timeline)."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)


def _sort_clips(clips: list[dict], mode: int) -> list[dict]:
    """Sort clips by mode: 0 = score descending, 1 = video time chronological."""
    if mode == 1:
        return sorted(clips, key=lambda c: (c.get("video_id", ""), c.get("start", 0.0)))
    return sorted(clips, key=lambda c: c.get("score", 0), reverse=True)


class _ResolveCheckWorker(QThread):
    result = Signal(bool, str, dict)  # connected, message, default_folders

    def run(self):
        try:
            from app.services.davinci_resolve import _get_resolve, get_working_folder_defaults
            resolve = _get_resolve()
            defaults = {}
            project = resolve.GetProjectManager().GetCurrentProject()
            if project:
                defaults = get_working_folder_defaults(project)
            self.result.emit(True, "Connected to DaVinci Resolve", defaults)
        except (ImportError, ConnectionError) as e:
            self.result.emit(False, str(e), {})


class _DaVinciCreateWorker(QThread):
    success = Signal()
    error = Signal(str)

    def __init__(
        self,
        project_name: str,
        otio_path: str,
        timeline_name: str,
        frame_rate: str,
        width: int,
        height: int,
        working_folders: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.project_name = project_name
        self.otio_path = otio_path
        self.timeline_name = timeline_name
        self.frame_rate = frame_rate
        self.width = width
        self.height = height
        self.working_folders = working_folders or {}

    def run(self):
        try:
            from app.services.davinci_resolve import create_project_with_timeline
            create_project_with_timeline(
                project_name=self.project_name,
                otio_path=self.otio_path,
                timeline_name=self.timeline_name,
                frame_rate=self.frame_rate,
                width=self.width,
                height=self.height,
                working_folders=self.working_folders,
            )
            self.success.emit()
        except Exception as e:
            self.error.emit(str(e))


class DaVinciProjectDialog(QDialog):
    """Dialog to configure and create a DaVinci Resolve project."""

    def __init__(self, highlights: list[dict], export_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create DaVinci Resolve Project")
        self.setMinimumWidth(560)
        self._highlights = highlights
        self._export_fn = export_fn  # callable(highlights, path) -> (exported, skipped)
        self._worker: _DaVinciCreateWorker | None = None
        self._check_worker: _ResolveCheckWorker | None = None
        self._tmp_path: str | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Status
        self.status_label = QLabel("Checking connection...")
        self.status_label.setObjectName("davinciStatus")
        layout.addWidget(self.status_label)

        # Form
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("My Project")
        form.addRow("Project Name:", self.name_input)

        self.timeline_input = QLineEdit("Highlights")
        form.addRow("Timeline Name:", self.timeline_input)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["By Score (highest first)", "By Video Time (chronological)"])
        self.sort_combo.setEnabled(len(self._highlights) > 1)
        form.addRow("Clip Order:", self.sort_combo)

        self.fps_combo = QComboBox()
        for fps in ("24", "25", "29.97", "29.97 DF", "30", "50", "59.94", "60"):
            self.fps_combo.addItem(fps)
        self.fps_combo.setCurrentText("25")
        form.addRow("Frame Rate:", self.fps_combo)

        self.res_combo = QComboBox()
        self.res_combo.addItems(["1920x1080", "3840x2160", "7680x4320", "Custom"])
        self.res_combo.setCurrentText("3840x2160")
        self.res_combo.currentTextChanged.connect(self._on_res_changed)
        form.addRow("Resolution:", self.res_combo)

        # Custom resolution row
        self.custom_w = QLineEdit()
        self.custom_w.setPlaceholderText("Width")
        self.custom_w.setFixedWidth(80)
        self._custom_x_label = QLabel("x")
        self.custom_h = QLineEdit()
        self.custom_h.setPlaceholderText("Height")
        self.custom_h.setFixedWidth(80)
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.custom_w)
        custom_row.addWidget(self._custom_x_label)
        custom_row.addWidget(self.custom_h)
        custom_row.addStretch()
        self.custom_w.setVisible(False)
        self._custom_x_label.setVisible(False)
        self.custom_h.setVisible(False)
        form.addRow("", custom_row)

        layout.addLayout(form)
        layout.addSpacing(8)

        # Working Folders
        folders_label = QLabel("Working Folders")
        folders_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(folders_label)

        folders_form = QFormLayout()
        self._folder_inputs: dict[str, QLineEdit] = {}
        for key, label in [
            ("projectMediaLocation", "Project media:"),
            ("cacheFilesLocation", "Cache files:"),
            ("galleryStillsLocation", "Gallery stills:"),
        ]:
            row = QHBoxLayout()
            line = QLineEdit()
            line.setPlaceholderText("(Resolve default)")
            browse_btn = QPushButton("Browse")
            browse_btn.setFixedWidth(80)
            browse_btn.clicked.connect(
                lambda checked, le=line: le.setText(
                    QFileDialog.getExistingDirectory(self, "Select Folder", le.text()) or le.text()
                )
            )
            row.addWidget(line, stretch=1)
            row.addWidget(browse_btn)
            folders_form.addRow(label, row)
            self._folder_inputs[key] = line
        layout.addLayout(folders_form)
        layout.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.create_btn = QPushButton("Create Project")
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.create_btn)
        layout.addLayout(btn_row)

    def _on_res_changed(self, text: str):
        custom = text == "Custom"
        self.custom_w.setVisible(custom)
        self._custom_x_label.setVisible(custom)
        self.custom_h.setVisible(custom)

    def _get_resolution(self) -> tuple[int, int]:
        if self.res_combo.currentText() == "Custom":
            return int(self.custom_w.text()), int(self.custom_h.text())
        parts = self.res_combo.currentText().split("x")
        return int(parts[0]), int(parts[1])

    # ── Connection check ──────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._check_connection()

    def _check_connection(self):
        self.status_label.setText("Checking connection...")
        self.status_label.setStyleSheet("color: #888;")
        self.create_btn.setEnabled(False)

        self._check_worker = _ResolveCheckWorker(self)
        self._check_worker.result.connect(self._on_check_result)
        self._check_worker.start()

    def _on_check_result(self, connected: bool, message: str, defaults: dict):
        if connected:
            self.status_label.setText("Connected to DaVinci Resolve")
            self.status_label.setStyleSheet("color: #27ae60;")
            self.create_btn.setEnabled(True)
            for key, line in self._folder_inputs.items():
                if key in defaults:
                    line.setPlaceholderText(defaults[key])
        else:
            self.status_label.setText(message)
            self.status_label.setStyleSheet("color: #e74c3c;")
            self.create_btn.setEnabled(False)

    # ── Create ────────────────────────────────────────────────────────

    def _on_create(self):
        name = self.name_input.text().strip()
        if not name:
            self.status_label.setText("Project name is required")
            self.status_label.setStyleSheet("color: #e74c3c;")
            return

        try:
            width, height = self._get_resolution()
        except (ValueError, IndexError):
            self.status_label.setText("Invalid resolution")
            self.status_label.setStyleSheet("color: #e74c3c;")
            return

        # Sort clips
        sorted_highlights = _sort_clips(self._highlights, self.sort_combo.currentIndex())

        # Export OTIO to temp file
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".otio")
            os.close(fd)
            self._tmp_path = tmp_path
            self._export_fn(sorted_highlights, tmp_path)
        except Exception as e:
            self.status_label.setText(f"OTIO export failed: {e}")
            self.status_label.setStyleSheet("color: #e74c3c;")
            self._cleanup_tmp()
            return

        self.create_btn.setEnabled(False)
        self.create_btn.setText("Creating...")
        self.status_label.setText("Creating project in Resolve...")
        self.status_label.setStyleSheet("color: #888;")

        timeline_name = self.timeline_input.text().strip() or "Highlights"
        frame_rate = self.fps_combo.currentText()

        working_folders = {
            k: v.text().strip()
            for k, v in self._folder_inputs.items()
            if v.text().strip()
        }

        self._worker = _DaVinciCreateWorker(
            project_name=name,
            otio_path=tmp_path,
            timeline_name=timeline_name,
            frame_rate=frame_rate,
            width=width,
            height=height,
            working_folders=working_folders,
            parent=self,
        )
        self._worker.success.connect(self._on_success)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._cleanup_tmp)
        self._worker.start()

    def _on_success(self):
        self.create_btn.setText("Create Project")
        self.accept()

    def _on_error(self, msg: str):
        self.create_btn.setEnabled(True)
        self.create_btn.setText("Create Project")
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    def _cleanup_tmp(self):
        if self._tmp_path and os.path.exists(self._tmp_path):
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
            self._tmp_path = None


# ── Append to existing timeline dialog ────────────────────────────


class _LoadProjectsWorker(QThread):
    result = Signal(bool, str, list)  # connected, message, project_names

    def run(self):
        try:
            from app.services.davinci_resolve import _get_resolve, list_projects
            _get_resolve()
            projects = list_projects()
            self.result.emit(True, "Connected to DaVinci Resolve", projects)
        except (ImportError, ConnectionError) as e:
            self.result.emit(False, str(e), [])


class _LoadTimelinesWorker(QThread):
    result = Signal(list)  # timeline names
    error = Signal(str)

    def __init__(self, project_name: str, parent=None):
        super().__init__(parent)
        self.project_name = project_name

    def run(self):
        try:
            from app.services.davinci_resolve import list_timelines
            names = list_timelines(self.project_name)
            self.result.emit(names)
        except Exception as e:
            self.error.emit(str(e))


class _AppendWorker(QThread):
    success = Signal(int)  # number of clips appended
    error = Signal(str)

    def __init__(self, project_name: str, timeline_name: str,
                 clips: list[dict], parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.timeline_name = timeline_name
        self.clips = clips

    def run(self):
        try:
            from app.services.davinci_resolve import append_to_timeline
            count = append_to_timeline(
                self.project_name, self.timeline_name, self.clips,
            )
            self.success.emit(count)
        except Exception as e:
            self.error.emit(str(e))


class DaVinciAppendDialog(QDialog):
    """Dialog to append highlights to an existing DaVinci Resolve timeline."""

    def __init__(self, highlights: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Append to DaVinci Resolve Timeline")
        self.setMinimumWidth(560)
        self._highlights = highlights
        self._workers: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Status
        self.status_label = QLabel("Checking connection...")
        self.status_label.setObjectName("davinciStatus")
        layout.addWidget(self.status_label)

        # Form
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)
        self.project_combo.setMinimumWidth(380)
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        form.addRow("Project:", self.project_combo)

        self.timeline_combo = QComboBox()
        self.timeline_combo.setEditable(True)
        self.timeline_combo.setEnabled(False)
        self.timeline_combo.setMinimumWidth(380)
        self.timeline_combo.lineEdit().setPlaceholderText("Select or type new name")
        form.addRow("Timeline:", self.timeline_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["By Score (highest first)", "By Video Time (chronological)"])
        self.sort_combo.setEnabled(len(self._highlights) > 1)
        form.addRow("Clip Order:", self.sort_combo)

        layout.addLayout(form)
        layout.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.append_btn = QPushButton("Append Clips")
        self.append_btn.setEnabled(False)
        self.append_btn.clicked.connect(self._on_append)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.append_btn)
        layout.addLayout(btn_row)

    # ── Connection + project loading ──────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._load_projects()

    def _load_projects(self):
        self.status_label.setText("Checking connection...")
        self.status_label.setStyleSheet("color: #888;")
        worker = _LoadProjectsWorker(self)
        worker.result.connect(self._on_projects_loaded)
        self._workers.append(worker)
        worker.start()

    def _on_projects_loaded(self, connected: bool, message: str, projects: list):
        if not connected:
            self.status_label.setText(message)
            self.status_label.setStyleSheet("color: #e74c3c;")
            return
        self.status_label.setText("Connected to DaVinci Resolve")
        self.status_label.setStyleSheet("color: #27ae60;")
        self.project_combo.setEnabled(True)
        self.project_combo.clear()
        for name in projects:
            self.project_combo.addItem(name)
        if projects:
            self._on_project_changed(projects[0])

    # ── Timeline loading ──────────────────────────────────────────

    def _on_project_changed(self, project_name: str):
        if not project_name:
            return
        self.timeline_combo.clear()
        self.timeline_combo.setEnabled(False)
        self.append_btn.setEnabled(False)
        self.status_label.setText(f"Loading timelines for '{project_name}'...")
        self.status_label.setStyleSheet("color: #888;")

        worker = _LoadTimelinesWorker(project_name, self)
        worker.result.connect(self._on_timelines_loaded)
        worker.error.connect(self._on_timeline_error)
        self._workers.append(worker)
        worker.start()

    def _on_timelines_loaded(self, names: list):
        self.timeline_combo.setEnabled(True)
        self.append_btn.setEnabled(True)
        self.timeline_combo.clear()
        for name in names:
            self.timeline_combo.addItem(name)
        if not names:
            self.timeline_combo.setEditText("Highlights")
        self.status_label.setText("Connected to DaVinci Resolve")
        self.status_label.setStyleSheet("color: #27ae60;")

    def _on_timeline_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    # ── Append ────────────────────────────────────────────────────

    def _on_append(self):
        project = self.project_combo.currentText()
        timeline = self.timeline_combo.currentText().strip()
        if not project or not timeline:
            self.status_label.setText("Select a project and timeline")
            self.status_label.setStyleSheet("color: #e74c3c;")
            return

        self.append_btn.setEnabled(False)
        self.append_btn.setText("Appending...")
        self.status_label.setText("Importing media and appending clips...")
        self.status_label.setStyleSheet("color: #888;")

        sorted_highlights = _sort_clips(self._highlights, self.sort_combo.currentIndex())
        worker = _AppendWorker(project, timeline, sorted_highlights, self)
        worker.success.connect(self._on_success)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_success(self, count: int):
        self.append_btn.setText("Append Clips")
        self.accept()
        msg = QMessageBox(self.parent())
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setWindowTitle("Success")
        msg.setText(f"Appended {count} clip(s) to timeline.")
        msg.exec()

    def _on_error(self, msg: str):
        self.append_btn.setEnabled(True)
        self.append_btn.setText("Append Clips")
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")
