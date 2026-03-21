"""DaVinci Color Grading Advisor — chat UI with screenshot capture.

The user asks questions about their footage, the advisor captures a screenshot
of Resolve (viewer + scopes), analyzes it, and gives beginner-friendly advice.
"""
from __future__ import annotations

import re
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.services.advisor_worker import AdvisorWorker
from app.services.advisor_prompts import ADVISOR_ACTIONS

logger = logging.getLogger(__name__)

# Max conversation screenshots to keep (older ones replaced with placeholder)
_MAX_SCREENSHOT_MESSAGES = 5

# Regex for parsing [DO:xxx] and [ACTION:xxx label] tags
_DO_PATTERN = re.compile(r'\[DO:(\w+)\]')
_ACTION_PATTERN = re.compile(r'\[ACTION:(\w+)\]\s*(.*?)(?:\n|$)')


class _ChatBubble(QLabel):
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
        self._current_bubble: _ChatBubble | None = None
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
        self.msg_layout.setSpacing(8)
        self.msg_layout.addStretch()
        self.scroll.setWidget(self.msg_container)
        layout.addWidget(self.scroll, stretch=1)

        # Input
        input_row = QHBoxLayout()
        from PySide6.QtWidgets import QLineEdit
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
        welcome = _ChatBubble(
            "Hi! I can see your DaVinci Resolve window and help with anything — "
            "editing, color grading, audio, effects, exporting, or just figuring "
            "out where things are.\n\n"
            "Make sure DaVinci Resolve is open, then ask away.",
            is_user=False,
        )
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, welcome,
                                     alignment=Qt.AlignmentFlag.AlignLeft)

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
        user_bubble = _ChatBubble(text, is_user=True)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, user_bubble,
                                     alignment=Qt.AlignmentFlag.AlignRight)

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
        self._current_bubble = _ChatBubble("...", is_user=False)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, self._current_bubble,
                                     alignment=Qt.AlignmentFlag.AlignLeft)
        self._scroll_to_bottom()

        # Start streaming
        self._worker = AdvisorWorker(list(self._conversation), self)
        self._worker.token.connect(self._on_token)
        self._worker.stream_done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_token(self, token: str):
        self._current_text += token
        if self._current_bubble:
            # Strip [DO:...] and [ACTION:...] tags from display
            display = _DO_PATTERN.sub('', self._current_text)
            display = _ACTION_PATTERN.sub('', display).strip()
            self._current_bubble.setText(display or "...")
        self._scroll_to_bottom()

    def _on_done(self, full_text: str):
        # Save assistant response to conversation
        self._conversation.append({"role": "assistant", "content": full_text})

        # Clean display text
        display = _DO_PATTERN.sub('', full_text)
        display = _ACTION_PATTERN.sub('', display).strip()
        if self._current_bubble:
            self._current_bubble.setText(display)

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

        # Show status
        action_names = {
            "switch_color_page": "Switched to Color page",
            "toggle_scopes": "Opened video scopes",
            "toggle_log_mode": "Switched to Log grading mode",
            "bypass_grades": "Toggled grade bypass",
        }
        for aid in executed:
            status = _StatusBubble(action_names.get(aid, f"Executed {aid}"))
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
        self._current_bubble = _ChatBubble("...", is_user=False)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, self._current_bubble,
                                     alignment=Qt.AlignmentFlag.AlignLeft)
        self._scroll_to_bottom()

        self._worker = AdvisorWorker(list(self._conversation), self)
        self._worker.token.connect(self._on_token)
        self._worker.stream_done.connect(self._on_follow_up_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_follow_up_done(self, full_text: str):
        """Handle the follow-up response after auto-actions."""
        self._conversation.append({"role": "assistant", "content": full_text})

        display = _DO_PATTERN.sub('', full_text)
        display = _ACTION_PATTERN.sub('', display).strip()
        if self._current_bubble:
            self._current_bubble.setText(display)

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
            action_names = {
                "switch_color_page": "Switched to Color page",
                "toggle_scopes": "Toggled video scopes",
                "toggle_log_mode": "Switched grading mode",
                "bypass_grades": "Toggled grade bypass",
            }
            status = _StatusBubble(action_names.get(action_id, f"Done: {action_id}"))
            self.msg_layout.insertWidget(self.msg_layout.count() - 1, status,
                                         alignment=Qt.AlignmentFlag.AlignLeft)
            self._scroll_to_bottom()
        except Exception as e:
            logger.warning("Action %s failed: %s", action_id, e)

    def _on_error(self, msg: str):
        if self._current_bubble:
            self._current_bubble.setText(f"Error: {msg}")
            self._current_bubble.setStyleSheet(
                "background: #7f1d1d; color: #fca5a5; border-radius: 10px; "
                "font-size: 13px; padding: 8px 12px;"
            )
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
