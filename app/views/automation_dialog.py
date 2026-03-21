"""Automation dialog — beginner-friendly UI for visual automation tasks.

Presents automation tasks as simple action cards. Hides all technical
details (nodes, graphs, etc.) behind intent-based actions like
"Isolate Subject" or "Apply Magic Mask".
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


class _PermissionCheckWorker(QThread):
    result = Signal(dict)  # permission name -> bool

    def run(self):
        try:
            from app.automation.permissions import check_all
            self.result.emit(check_all())
        except Exception:
            self.result.emit({})


class _AutomationWorker(QThread):
    """Runs automation steps in a background thread."""
    step_progress = Signal(str, str, str)  # step_name, status, message
    finished_ok = Signal(list)  # list of StepResult
    error = Signal(str)

    def __init__(self, task_name: str, parent=None):
        super().__init__(parent)
        self.task_name = task_name

    def run(self):
        try:
            from app.automation.engine import AutomationEngine

            if self.task_name == "magic_mask":
                from app.automation.tasks.magic_mask import build_steps
                steps = build_steps()
            else:
                self.error.emit(f"Unknown task: {self.task_name}")
                return

            engine = AutomationEngine(
                on_step_progress=lambda name, status, msg: (
                    self.step_progress.emit(name, status, msg)
                ),
            )
            results = engine.run_steps(steps)
            self.finished_ok.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class _TaskCard(QWidget):
    """A simple card representing an automation task."""
    run_requested = Signal(str)  # task_name

    def __init__(self, task_name: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.task_name = task_name
        self.setObjectName("automationCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(desc_label)

        self.run_btn = QPushButton("Run")
        self.run_btn.setFixedWidth(80)
        self.run_btn.clicked.connect(lambda: self.run_requested.emit(self.task_name))
        layout.addWidget(self.run_btn, alignment=Qt.AlignmentFlag.AlignRight)


class AutomationDialog(QDialog):
    """Dialog for running visual automation tasks on DaVinci Resolve."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Automation")
        self.setMinimumSize(500, 400)
        self._workers: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Status bar for permissions / progress
        self.status_label = QLabel("Checking permissions...")
        self.status_label.setObjectName("davinciStatus")
        layout.addWidget(self.status_label)

        # Progress area
        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet("color: #888; font-size: 12px;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Task cards in a scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setSpacing(8)

        # MVP task card — beginner-friendly language
        card = _TaskCard(
            task_name="magic_mask",
            title="Isolate Subject",
            description=(
                "Automatically isolates the main subject in your clip "
                "using DaVinci Resolve's Magic Mask. Great for applying "
                "color corrections to just the person or background."
            ),
        )
        card.run_requested.connect(self._on_run_task)
        self.cards_layout.addWidget(card)

        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_widget)
        layout.addWidget(scroll, stretch=1)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def showEvent(self, event):
        super().showEvent(event)
        self._check_permissions()

    def _check_permissions(self):
        self.status_label.setText("Checking permissions...")
        self.status_label.setStyleSheet("color: #888;")
        worker = _PermissionCheckWorker(self)
        worker.result.connect(self._on_permissions_checked)
        self._workers.append(worker)
        worker.start()

    def _on_permissions_checked(self, perms: dict):
        if not perms:
            self.status_label.setText(
                "Could not check permissions. "
                "Make sure pyobjc frameworks are installed."
            )
            self.status_label.setStyleSheet("color: #e74c3c;")
            return

        missing = [name for name, ok in perms.items() if not ok]
        if missing:
            names = ", ".join(missing)
            self.status_label.setText(
                f"Missing permissions: {names}. "
                "Grant them in System Settings → Privacy & Security."
            )
            self.status_label.setStyleSheet("color: #e74c3c;")
        else:
            self.status_label.setText("All permissions granted")
            self.status_label.setStyleSheet("color: #27ae60;")

    def _on_run_task(self, task_name: str):
        # Disable all run buttons during execution
        for i in range(self.cards_layout.count()):
            widget = self.cards_layout.itemAt(i).widget()
            if isinstance(widget, _TaskCard):
                widget.run_btn.setEnabled(False)

        self.progress_label.setVisible(True)
        self.progress_label.setText("Starting automation...")
        self.status_label.setText("Running...")
        self.status_label.setStyleSheet("color: #888;")

        worker = _AutomationWorker(task_name, self)
        worker.step_progress.connect(self._on_step_progress)
        worker.finished_ok.connect(self._on_task_finished)
        worker.error.connect(self._on_task_error)
        self._workers.append(worker)
        worker.start()

    def _on_step_progress(self, step_name: str, status: str, message: str):
        icon = {
            "running": "▶",
            "verifying": "🔍",
            "passed": "✓",
            "failed": "✗",
            "retrying": "↻",
        }.get(status, "·")
        self.progress_label.setText(f"{icon} {step_name}: {message}")

    def _on_task_finished(self, results):
        self._enable_cards()
        all_passed = all(r.success for r in results)
        if all_passed:
            self.status_label.setText("Automation complete")
            self.status_label.setStyleSheet("color: #27ae60;")
            self.progress_label.setText(
                f"All {len(results)} steps completed successfully."
            )
        else:
            failed = next(r for r in results if not r.success)
            self.status_label.setText("Automation stopped")
            self.status_label.setStyleSheet("color: #e74c3c;")
            self.progress_label.setText(
                f"Failed at '{failed.name}': {failed.message}"
            )

    def _on_task_error(self, msg: str):
        self._enable_cards()
        self.status_label.setText("Error")
        self.status_label.setStyleSheet("color: #e74c3c;")
        self.progress_label.setText(msg)

    def _enable_cards(self):
        for i in range(self.cards_layout.count()):
            item = self.cards_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), _TaskCard):
                item.widget().run_btn.setEnabled(True)
