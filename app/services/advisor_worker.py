"""QThread worker for the DaVinci Color Grading Advisor.

Calls the Anthropic Messages API with streaming and vision support.
Each call receives the full conversation history and an optional screenshot.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from app.config import get_anthropic_api_key, get_vision_model
from app.services.advisor_prompts import ADVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class AdvisorWorker(QThread):
    """Streams a response from Claude given conversation history + screenshot."""
    token = Signal(str)
    stream_done = Signal(str)   # full response text
    error = Signal(str)

    def __init__(self, conversation: list[dict], parent=None):
        super().__init__(parent)
        self.conversation = conversation

    def run(self):
        try:
            import anthropic
            api_key = get_anthropic_api_key()
            if not api_key:
                self.error.emit("Anthropic API key not set. Add it in Settings.")
                return

            client = anthropic.Anthropic(api_key=api_key)
            full_text = ""

            with client.messages.stream(
                model=get_vision_model(),
                max_tokens=1024,
                system=ADVISOR_SYSTEM_PROMPT,
                messages=self.conversation,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    self.token.emit(text)

            self.stream_done.emit(full_text)

        except Exception as e:
            logger.error("Advisor error: %s", e)
            self.error.emit(str(e))
