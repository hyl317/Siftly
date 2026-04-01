"""QThread worker for extracting text and images from user-provided DaVinci manual PDFs."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class ManualTextExtractWorker(QThread):
    """Extract text + images from PDFs and cache locally."""
    progress = Signal(int, int)  # current_page, total_pages
    done = Signal(int)           # total chunks aligned
    error = Signal(str)

    def __init__(self, pdf_paths: list[str], parent=None):
        super().__init__(parent)
        self.pdf_paths = pdf_paths

    def run(self):
        try:
            from app.services.knowledge_base import extract_and_cache

            def on_progress(current, total):
                self.progress.emit(current, total)

            aligned = extract_and_cache(self.pdf_paths, progress_fn=on_progress)
            self.done.emit(aligned)
        except Exception as e:
            self.error.emit(str(e))
