"""DaVinci Color Grading Advisor — chat UI with screenshot capture.

The user asks questions about their footage, the advisor captures a screenshot
of Resolve (viewer + scopes), analyzes it, and gives beginner-friendly advice.
"""
from __future__ import annotations

import re
import logging
import markdown

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from app.services.advisor_worker import AdvisorWorker
from app.services.advisor_prompts import ADVISOR_ACTIONS

logger = logging.getLogger(__name__)

# Max conversation screenshots to keep (older ones replaced with placeholder)
_MAX_SCREENSHOT_MESSAGES = 5

# Regex for parsing [DO:xxx] and [ACTION:xxx label] tags
_DO_PATTERN = re.compile(r'\[DO:(\w+)\]')
_ACTION_PATTERN = re.compile(r'\[ACTION:(\w+)\]\s*(.*?)(?:\n|$)')

_ACTION_NAMES = {
    "switch_color_page": "Switched to Color page",
    "toggle_scopes": "Toggled video scopes",
    "toggle_log_mode": "Switched grading mode",
    "bypass_grades": "Toggled grade bypass",
}

_BUBBLE_VERTICAL_PADDING = 22  # top+bottom padding + border


def _strip_tags(text: str) -> str:
    """Remove [DO:...] and [ACTION:...] tags from display text."""
    text = _DO_PATTERN.sub('', text)
    return _ACTION_PATTERN.sub('', text).strip()


# Shared CSS for the HTML inside QTextBrowser bubbles
_MESSAGE_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 13px;
    line-height: 1.55;
    margin: 0;
    padding: 0;
}
p { margin: 0 0 8px 0; }
p:last-child { margin-bottom: 0; }
ul, ol { margin: 4px 0 8px 0; padding-left: 20px; }
li { margin-bottom: 3px; }
code {
    background: rgba(255,255,255,0.08);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'SF Mono', 'Menlo', monospace;
    font-size: 12px;
}
pre {
    background: rgba(0,0,0,0.3);
    padding: 10px 12px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 6px 0;
}
pre code {
    background: none;
    padding: 0;
}
strong, b { font-weight: 600; }
h1, h2, h3, h4 {
    font-weight: 600;
    margin: 10px 0 4px 0;
}
h3 { font-size: 14px; }
h4 { font-size: 13px; }
"""


def _md_to_html(text: str, fg_color: str = "#e5e7eb") -> str:
    """Convert markdown text to styled HTML for QTextBrowser."""
    html = markdown.markdown(
        text,
        extensions=["fenced_code", "nl2br", "sane_lists"],
    )
    return (
        f"<html><head><style>{_MESSAGE_CSS}\n"
        f"body {{ color: {fg_color}; }}\n"
        f"</style></head><body>{html}</body></html>"
    )


class _ChatBubble(QTextBrowser):
    """Auto-sizing rich-text chat message widget."""

    _BUBBLE_BASE = (
        "QTextBrowser {"
        "  border-radius: 12px; border: none; padding: 10px 14px;"
        "  background: %s; color: %s;"
        "}"
    )

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self._is_user = is_user
        self._fg = "#ffffff" if is_user else "#e5e7eb"
        bg = "#2563eb" if is_user else "#1e1e2e"

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(self._BUBBLE_BASE % (bg, self._fg))
        self.setHtml(_md_to_html(text, self._fg))
        self._update_height()

        # Throttle rendering during streaming to avoid per-token markdown parses
        self._pending_text: str | None = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._flush_pending)

    def set_markdown_text(self, text: str):
        """Queue a markdown render (throttled during streaming)."""
        self._pending_text = text
        if not self._render_timer.isActive():
            self._render_timer.start()

    def set_markdown_text_immediate(self, text: str):
        """Render markdown immediately (for final text, errors)."""
        self._pending_text = None
        self._render_timer.stop()
        self.setHtml(_md_to_html(text, self._fg))
        self._update_height()

    def _flush_pending(self):
        if self._pending_text is not None:
            text = self._pending_text
            self._pending_text = None
            self.setHtml(_md_to_html(text, self._fg))
            self._update_height()

    def _update_height(self):
        doc = self.document()
        doc.setTextWidth(self.viewport().width())
        h = int(doc.size().height()) + _BUBBLE_VERTICAL_PADDING
        self.setFixedHeight(max(h, 36))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_height()


class _MessageRow(QWidget):
    """Full-width row containing a chat bubble with proper alignment."""

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.bubble = _ChatBubble(text, is_user)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if is_user:
            # Right-aligned, capped width
            layout.addSpacing(80)
            layout.addWidget(self.bubble, stretch=1)
        else:
            # Left-aligned, full width
            layout.addWidget(self.bubble, stretch=1)
            layout.addSpacing(40)


class _StatusBubble(QLabel):
    """Small inline status message (e.g., 'Opened video scopes')."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "color: #64ffda; font-size: 11px; font-style: italic; padding: 2px 8px;"
        )


class _ActionButton(QPushButton):
    """Clickable action button parsed from [ACTION:xxx] tags."""
    def __init__(self, action_id: str, label: str, parent=None):
        super().__init__(label.strip() or action_id, parent)
        self.action_id = action_id
        self.setStyleSheet(
            "background: #1a3a2a; border: 1px solid #2a5a3a; color: #27ae60; "
            "font-size: 11px; padding: 4px 12px; border-radius: 4px;"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class AdvisorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._conversation: list[dict] = []
        self._worker: AdvisorWorker | None = None
        self._current_row: _MessageRow | None = None
        self._current_text = ""
        self._pending_user_question = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header = QHBoxLayout()
        title = QLabel("DaVinci Resolve Assistant")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.auto_capture_cb = QCheckBox("Auto-capture screenshot")
        self.auto_capture_cb.setChecked(True)
        self.auto_capture_cb.setToolTip(
            "Automatically capture a screenshot of DaVinci Resolve with each message.\n"
            "Uncheck to save API cost for follow-up questions that don't need a fresh screenshot."
        )
        header.addWidget(self.auto_capture_cb)

        self.new_convo_btn = QPushButton("New Conversation")
        self.new_convo_btn.clicked.connect(self._new_conversation)
        header.addWidget(self.new_convo_btn)
        layout.addLayout(header)

        # Status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.status_label)

        # Chat area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.msg_container = QWidget()
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.msg_layout.setSpacing(10)
        self.msg_layout.addStretch()
        self.scroll.setWidget(self.msg_container)
        layout.addWidget(self.scroll, stretch=1)

        # Input
        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(
            "Ask about your footage — e.g. 'Is my exposure okay?' or 'The colors look too warm'"
        )
        self.input_field.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input_field, stretch=1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        # Welcome message
        welcome = _MessageRow(
            "Hi! I can see your DaVinci Resolve window and help with anything — "
            "editing, color grading, audio, effects, exporting, or just figuring "
            "out where things are.\n\n"
            "Make sure DaVinci Resolve is open, then ask away.",
            is_user=False,
        )
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, welcome)

    def _new_conversation(self):
        self._conversation.clear()
        # Clear chat bubbles
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.status_label.setText("")

    def _capture_screenshot(self):
        """Capture Resolve window, return base64 PNG or None."""
        try:
            from app.automation.screen_capture import capture_window, get_resolve_window_id
            from app.automation.vision import _image_to_base64

            wid = get_resolve_window_id()
            if wid is None:
                self.status_label.setText("DaVinci Resolve not found — responding without screenshot")
                return None

            img = capture_window(wid)
            # Resize for cost efficiency
            max_w = 1568
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)))

            self.status_label.setText(f"Captured screenshot ({img.width}x{img.height})")
            return _image_to_base64(img)
        except Exception as e:
            logger.warning("Screenshot capture failed: %s", e)
            self.status_label.setText(f"Screenshot failed: {e}")
            return None

    def _send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        self._pending_user_question = text

        # Add user bubble
        user_row = _MessageRow(text, is_user=True)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, user_row)

        # Build user message content
        content: list[dict] = []
        if self.auto_capture_cb.isChecked():
            b64 = self._capture_screenshot()
            if b64:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64},
                })
        content.append({"type": "text", "text": text})

        self._conversation.append({"role": "user", "content": content})
        self._trim_old_screenshots()

        # Prepare assistant bubble
        self._current_text = ""
        self._current_row = _MessageRow("...", is_user=False)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, self._current_row)
        self._scroll_to_bottom()

        # Start streaming
        self._worker = AdvisorWorker(list(self._conversation), self)
        self._worker.token.connect(self._on_token)
        self._worker.stream_done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_token(self, token: str):
        self._current_text += token
        if self._current_row:
            display = _strip_tags(self._current_text)
            self._current_row.bubble.set_markdown_text(display or "...")
        self._scroll_to_bottom()

    def _on_done(self, full_text: str):
        # Save assistant response to conversation
        self._conversation.append({"role": "assistant", "content": full_text})

        display = _strip_tags(full_text)
        if self._current_row:
            self._current_row.bubble.set_markdown_text_immediate(display)

        # Check for [DO:xxx] auto-actions
        do_actions = _DO_PATTERN.findall(full_text)
        if do_actions:
            self._execute_do_actions(do_actions)
            return  # _execute_do_actions will re-enable input after follow-up

        # Parse [ACTION:xxx] tags and render buttons
        actions = _ACTION_PATTERN.findall(full_text)
        if actions:
            self._render_action_buttons(actions)

        self._enable_input()

    def _execute_do_actions(self, action_ids: list[str]):
        """Execute auto-actions, capture fresh screenshot, ask Claude to continue."""
        import time
        from app.automation.input_control import press_key

        executed = []
        for action_id in action_ids:
            shortcut = ADVISOR_ACTIONS.get(action_id)
            if shortcut:
                key, mods = shortcut
                try:
                    press_key(key, mods)
                    time.sleep(0.5)  # Let UI settle
                    executed.append(action_id)
                except Exception as e:
                    logger.warning("Failed to execute [DO:%s]: %s", action_id, e)

        if not executed:
            self._enable_input()
            return

        for aid in executed:
            status = _StatusBubble(_ACTION_NAMES.get(aid, f"Executed {aid}"))
            self.msg_layout.insertWidget(self.msg_layout.count() - 1, status,
                                         alignment=Qt.AlignmentFlag.AlignLeft)

        # Capture fresh screenshot and ask Claude to continue
        b64 = self._capture_screenshot()
        content: list[dict] = []
        if b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
        content.append({
            "type": "text",
            "text": (
                f"I've done that ({', '.join(executed)}). "
                "Here's the updated view. Now please answer the user's question."
            ),
        })
        self._conversation.append({"role": "user", "content": content})
        self._trim_old_screenshots()

        # New assistant bubble for the follow-up
        self._current_text = ""
        self._current_row = _MessageRow("...", is_user=False)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, self._current_row)
        self._scroll_to_bottom()

        self._worker = AdvisorWorker(list(self._conversation), self)
        self._worker.token.connect(self._on_token)
        self._worker.stream_done.connect(self._on_follow_up_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_follow_up_done(self, full_text: str):
        """Handle the follow-up response after auto-actions."""
        self._conversation.append({"role": "assistant", "content": full_text})

        display = _strip_tags(full_text)
        if self._current_row:
            self._current_row.bubble.set_markdown_text_immediate(display)

        actions = _ACTION_PATTERN.findall(full_text)
        if actions:
            self._render_action_buttons(actions)

        self._enable_input()

    def _render_action_buttons(self, actions: list[tuple[str, str]]):
        """Render [ACTION:xxx label] as clickable buttons."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for action_id, label in actions:
            if action_id not in ADVISOR_ACTIONS:
                continue
            btn = _ActionButton(action_id, label)
            btn.clicked.connect(lambda checked, aid=action_id: self._on_action_clicked(aid))
            row.addWidget(btn)
        row.addStretch()

        container = QWidget()
        container.setLayout(row)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, container)

    def _on_action_clicked(self, action_id: str):
        """Execute an action button click."""
        from app.automation.input_control import press_key

        shortcut = ADVISOR_ACTIONS.get(action_id)
        if not shortcut:
            return
        key, mods = shortcut
        try:
            press_key(key, mods)
            status = _StatusBubble(_ACTION_NAMES.get(action_id, f"Done: {action_id}"))
            self.msg_layout.insertWidget(self.msg_layout.count() - 1, status,
                                         alignment=Qt.AlignmentFlag.AlignLeft)
            self._scroll_to_bottom()
        except Exception as e:
            logger.warning("Action %s failed: %s", action_id, e)

    def _on_error(self, msg: str):
        if self._current_row:
            self._current_row.bubble.setStyleSheet(
                _ChatBubble._BUBBLE_BASE % ("#7f1d1d", "#fca5a5")
            )
            self._current_row.bubble.set_markdown_text_immediate(f"Error: {msg}")
        self._enable_input()

    def _enable_input(self):
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()
        self.status_label.setText("")

    def _trim_old_screenshots(self):
        """Replace old screenshots with placeholder text to save context tokens."""
        image_count = 0
        for msg in reversed(self._conversation):
            if not isinstance(msg.get("content"), list):
                continue
            for i, block in enumerate(msg["content"]):
                if isinstance(block, dict) and block.get("type") == "image":
                    image_count += 1
                    if image_count > _MAX_SCREENSHOT_MESSAGES:
                        msg["content"][i] = {
                            "type": "text",
                            "text": "[previous screenshot omitted]",
                        }

    def _scroll_to_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
