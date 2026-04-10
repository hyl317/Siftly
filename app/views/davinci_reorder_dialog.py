"""Dialog for AI-powered timeline reordering in DaVinci Resolve."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListView, QMessageBox, QPushButton, QVBoxLayout,
)


class _ResolveCheckWorker(QThread):
    result = Signal(bool, str)

    def run(self):
        try:
            from app.services.davinci_resolve import _get_resolve
            _get_resolve()
            self.result.emit(True, "Connected to DaVinci Resolve")
        except (ImportError, ConnectionError) as e:
            self.result.emit(False, str(e))


class _LoadProjectsWorker(QThread):
    result = Signal(bool, str, list)

    def run(self):
        try:
            from app.services.davinci_resolve import _get_resolve, list_projects
            _get_resolve()
            projects = list_projects()
            self.result.emit(True, "Connected to DaVinci Resolve", projects)
        except (ImportError, ConnectionError) as e:
            self.result.emit(False, str(e), [])


class _LoadTimelinesWorker(QThread):
    result = Signal(list)
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


class _ReadClipsWorker(QThread):
    result = Signal(list)  # list of clip dicts
    error = Signal(str)

    def __init__(self, project_name: str, timeline_name: str, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.timeline_name = timeline_name

    def run(self):
        try:
            from app.services.davinci_resolve import read_timeline_clips
            clips = read_timeline_clips(self.project_name, self.timeline_name)
            self.result.emit(clips)
        except Exception as e:
            self.error.emit(str(e))


class _CreateReorderedWorker(QThread):
    success = Signal(int)  # clips appended
    error = Signal(str)

    def __init__(self, project_name: str, new_timeline_name: str,
                 ordered_clips: list, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.new_timeline_name = new_timeline_name
        self.ordered_clips = ordered_clips

    def run(self):
        try:
            from app.services.davinci_resolve import create_reordered_timeline
            count = create_reordered_timeline(
                self.project_name, self.new_timeline_name, self.ordered_clips,
            )
            self.success.emit(count)
        except Exception as e:
            self.error.emit(str(e))


class DaVinciReorderDialog(QDialog):
    """Dialog to reorder clips on a DaVinci Resolve timeline using AI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reorder Timeline with AI")
        self.setMinimumWidth(640)
        self._workers: list = []
        self._timeline_clips: list[dict] = []
        self._storyline_worker = None
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
        self.project_combo.setView(QListView())
        self.project_combo.setEnabled(False)
        self.project_combo.setMinimumWidth(380)
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        form.addRow("Project:", self.project_combo)

        self.timeline_combo = QComboBox()
        self.timeline_combo.setView(QListView())
        self.timeline_combo.setEnabled(False)
        self.timeline_combo.setMinimumWidth(380)
        self.timeline_combo.currentTextChanged.connect(self._on_timeline_changed)
        form.addRow("Timeline:", self.timeline_combo)

        self.clips_label = QLabel("")
        form.addRow("Clips found:", self.clips_label)

        self.new_name_input = QLineEdit()
        self.new_name_input.setPlaceholderText("(auto-generated)")
        form.addRow("New timeline name:", self.new_name_input)

        layout.addLayout(form)
        layout.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.reorder_btn = QPushButton("Reorder Clips")
        self.reorder_btn.setMinimumWidth(140)
        self.reorder_btn.setEnabled(False)
        self.reorder_btn.clicked.connect(self._on_reorder)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.reorder_btn)
        layout.addLayout(btn_row)

    # ── Connection + project loading ─────────────────────────────

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

    # ── Timeline loading ─────────────────────────────────────────

    def _on_project_changed(self, project_name: str):
        if not project_name:
            return
        self.timeline_combo.clear()
        self.timeline_combo.setEnabled(False)
        self.reorder_btn.setEnabled(False)
        self.clips_label.setText("")
        self._timeline_clips = []
        self.status_label.setText(f"Loading timelines for '{project_name}'...")
        self.status_label.setStyleSheet("color: #888;")

        worker = _LoadTimelinesWorker(project_name, self)
        worker.result.connect(self._on_timelines_loaded)
        worker.error.connect(self._on_timeline_error)
        self._workers.append(worker)
        worker.start()

    def _on_timelines_loaded(self, names: list):
        self.timeline_combo.setEnabled(True)
        self.timeline_combo.clear()
        for name in names:
            self.timeline_combo.addItem(name)
        if names:
            self._on_timeline_changed(names[0])
        self.status_label.setText("Connected to DaVinci Resolve")
        self.status_label.setStyleSheet("color: #27ae60;")

    def _on_timeline_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    # ── Read clips on timeline selection ──────────────────────────

    def _on_timeline_changed(self, timeline_name: str):
        if not timeline_name:
            return
        project = self.project_combo.currentText()
        if not project:
            return

        self.clips_label.setText("Reading...")
        self.reorder_btn.setEnabled(False)

        # Auto-fill new timeline name
        if not self.new_name_input.text().strip():
            self.new_name_input.setPlaceholderText(
                f"{timeline_name} (AI Reordered)")

        worker = _ReadClipsWorker(project, timeline_name, self)
        worker.result.connect(self._on_clips_read)
        worker.error.connect(self._on_clips_error)
        self._workers.append(worker)
        worker.start()

    def _on_clips_read(self, clips: list):
        self._timeline_clips = clips
        self.clips_label.setText(str(len(clips)))
        self.reorder_btn.setEnabled(len(clips) > 1)
        if len(clips) <= 1:
            self.status_label.setText(
                "Need at least 2 clips to reorder")
            self.status_label.setStyleSheet("color: #888;")

    def _on_clips_error(self, msg: str):
        self.clips_label.setText("Error")
        self.status_label.setText(f"Error reading clips: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    # ── Reorder ──────────────────────────────────────────────────

    def _on_reorder(self):
        if not self._timeline_clips:
            return

        self.reorder_btn.setEnabled(False)
        self.reorder_btn.setText("Analyzing clips...")
        self.status_label.setStyleSheet("color: #888;")

        from app.services.storyline_worker import StorylineWorker
        self._storyline_worker = StorylineWorker(
            timeline_clips=self._timeline_clips, parent=self,
        )
        self._storyline_worker.progress.connect(
            lambda s: self.status_label.setText(s))
        self._storyline_worker.finished.connect(self._on_ordering_done)
        self._storyline_worker.error.connect(self._on_ordering_error)
        self._workers.append(self._storyline_worker)
        self._storyline_worker.start()

    def _on_ordering_done(self, ordered_clips: list):
        self.status_label.setText("Creating reordered timeline...")
        self.reorder_btn.setText("Creating timeline...")

        project = self.project_combo.currentText()
        new_name = (self.new_name_input.text().strip()
                    or f"{self.timeline_combo.currentText()} (AI Reordered)")

        worker = _CreateReorderedWorker(
            project, new_name, ordered_clips, self,
        )
        worker.success.connect(self._on_reorder_success)
        worker.error.connect(self._on_reorder_error)
        self._workers.append(worker)
        worker.start()

    def _on_ordering_error(self, msg: str):
        self.reorder_btn.setEnabled(True)
        self.reorder_btn.setText("Reorder Clips")
        self.status_label.setText(f"AI ordering failed: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")

    def _on_reorder_success(self, count: int):
        self.reorder_btn.setText("Reorder Clips")
        new_name = (self.new_name_input.text().strip()
                    or f"{self.timeline_combo.currentText()} (AI Reordered)")
        self.accept()
        msg = QMessageBox(self.parent())
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setWindowTitle("Success")
        msg.setText(
            f"Created timeline '{new_name}' with {count} clip(s) "
            f"in AI-determined order."
        )
        msg.exec()

    def _on_reorder_error(self, msg: str):
        self.reorder_btn.setEnabled(True)
        self.reorder_btn.setText("Reorder Clips")
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c;")
