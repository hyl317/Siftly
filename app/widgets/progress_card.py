from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout


class ProgressCard(QFrame):
    cancel_requested = Signal()

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setObjectName("progressCard")
        self.setMinimumHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)

        info_layout = QVBoxLayout()
        self.name_label = QLabel(filename)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.status_label = QLabel("Queued")
        self.status_label.setStyleSheet("font-size: 11px; color: #888;")
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(120)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelUploadBtn")
        self.cancel_btn.setFixedHeight(24)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setToolTip("Cancel upload")
        self.cancel_btn.clicked.connect(self._cancel)

        self.dismiss_btn = QPushButton("\u2715")
        self.dismiss_btn.setObjectName("dismissBtn")
        self.dismiss_btn.setFixedSize(24, 24)
        self.dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dismiss_btn.setToolTip("Dismiss")
        self.dismiss_btn.clicked.connect(self._dismiss)
        self.dismiss_btn.setVisible(False)

        layout.addLayout(info_layout, stretch=1)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.dismiss_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def update_status(self, status: str, percent: int):
        self.status_label.setText(status)
        if percent >= 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate

    def mark_error(self, message: str):
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("font-size: 11px; color: #e74c3c;")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.cancel_btn.setVisible(False)
        self.dismiss_btn.setVisible(True)

    def mark_done(self):
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet("font-size: 11px; color: #27ae60;")
        self.progress_bar.setValue(100)
        self.cancel_btn.setVisible(False)
        self.dismiss_btn.setVisible(True)

    def mark_cancelled(self):
        self.status_label.setText("Cancelled")
        self.status_label.setStyleSheet("font-size: 11px; color: #888;")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.cancel_btn.setVisible(False)
        self.dismiss_btn.setVisible(True)

    def _cancel(self):
        self.cancel_requested.emit()

    def _dismiss(self):
        self.setParent(None)
        self.deleteLater()
