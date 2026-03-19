from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.services.api_client import get_client


class AnalysisWorker(QThread):
    """Handles analyze calls (chat, summary, gist) — non-streaming."""
    result = Signal(str)
    error = Signal(str)

    def __init__(self, video_id: str, prompt: str, response_format: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.prompt = prompt
        self.response_format = response_format

    def run(self):
        try:
            client = get_client()
            kwargs = {
                "video_id": self.video_id,
                "prompt": self.prompt,
            }
            if self.response_format:
                kwargs["response_format"] = self.response_format

            res = client.analyze(**kwargs)
            self.result.emit(res.data)
        except Exception as e:
            self.error.emit(str(e))


class StreamingAnalysisWorker(QThread):
    """Handles streaming analyze calls for chat."""
    token = Signal(str)
    stream_done = Signal()
    error = Signal(str)

    def __init__(self, video_id: str, prompt: str, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.prompt = prompt

    def run(self):
        try:
            client = get_client()
            stream = client.analyze_stream(
                video_id=self.video_id,
                prompt=self.prompt,
            )
            for event in stream:
                if event.event_type == "text_generation":
                    self.token.emit(event.text)
            self.stream_done.emit()
        except Exception as e:
            self.error.emit(str(e))
