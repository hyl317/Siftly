from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.services.analysis_worker import StreamingAnalysisWorker


class ChatBubble(QLabel):
    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setContentsMargins(10, 8, 10, 8)
        if is_user:
            self.setStyleSheet(
                "background: #3b82f6; color: white; border-radius: 10px; "
                "font-size: 13px; padding: 8px 12px;"
            )
        else:
            self.setStyleSheet(
                "background: #374151; color: #e5e7eb; border-radius: 10px; "
                "font-size: 13px; padding: 8px 12px;"
            )


class ChatWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_id = ""
        self._worker: StreamingAnalysisWorker | None = None
        self._current_bubble: ChatBubble | None = None
        self._current_text = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scrollable messages
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.msg_container = QWidget()
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.msg_layout.setSpacing(8)
        self.msg_layout.addStretch()
        self.scroll.setWidget(self.msg_container)
        layout.addWidget(self.scroll, stretch=1)

        # Input
        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask a question about this video...")
        self.input_field.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input_field, stretch=1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

    def set_video_id(self, video_id: str):
        self._video_id = video_id
        # Clear history
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _send(self):
        text = self.input_field.text().strip()
        if not text or not self._video_id:
            return
        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)

        # Add user bubble
        user_bubble = ChatBubble(text, is_user=True)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, user_bubble,
                                     alignment=Qt.AlignmentFlag.AlignRight)

        # Prepare assistant bubble
        self._current_text = ""
        self._current_bubble = ChatBubble("...", is_user=False)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, self._current_bubble,
                                     alignment=Qt.AlignmentFlag.AlignLeft)
        self._scroll_to_bottom()

        # Start streaming
        self._worker = StreamingAnalysisWorker(self._video_id, text, self)
        self._worker.token.connect(self._on_token)
        self._worker.stream_done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_token(self, token: str):
        self._current_text += token
        if self._current_bubble:
            self._current_bubble.setText(self._current_text)
        self._scroll_to_bottom()

    def _on_done(self):
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()

    def _on_error(self, msg: str):
        if self._current_bubble:
            self._current_bubble.setText(f"Error: {msg}")
            self._current_bubble.setStyleSheet(
                "background: #7f1d1d; color: #fca5a5; border-radius: 10px; "
                "font-size: 13px; padding: 8px 12px;"
            )
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)

    def _scroll_to_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
