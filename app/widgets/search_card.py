from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.config import PROJECT_ROOT
from app.utils.thumbnails import extract_thumbnail
from app import video_map

THUMB_DIR = PROJECT_ROOT / ".thumbnails"


class _ThumbWorker(QThread):
    ready = Signal(str)  # path to extracted thumbnail

    def __init__(self, video_path: str, output_path: Path, time_sec: float, parent=None):
        super().__init__(parent)
        self._video_path = video_path
        self._output_path = output_path
        self._time_sec = time_sec

    def run(self):
        extract_thumbnail(Path(self._video_path), self._output_path, time_sec=self._time_sec)
        if self._output_path.exists():
            self.ready.emit(str(self._output_path))


def _fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _score_color(score: float) -> str:
    if score >= 70:
        return "#27ae60"
    elif score >= 40:
        return "#f39c12"
    else:
        return "#e74c3c"


class SearchCard(QFrame):
    play_clicked = Signal(str, float, float)  # video_id, start, end

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("highlightCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)

        self.result_data = result
        self._video_id = result.get("video_id", "")
        self._start = result.get("start", 0.0)
        self._end = result.get("end", 0.0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Thumbnail
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(80, 48)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_worker: _ThumbWorker | None = None
        local_path_for_thumb = video_map.get_path(self._video_id) or ""
        start_int = int(self._start)
        clip_thumb_path = THUMB_DIR / f"{self._video_id}_{start_int}.jpg"
        if clip_thumb_path.exists():
            self._set_thumb_pixmap(str(clip_thumb_path))
        elif local_path_for_thumb:
            self._thumb_label.setText("...")
            self._thumb_label.setStyleSheet(
                "background: #0f1a2e; border-radius: 4px; color: #888; font-size: 11px;"
            )
            self._thumb_worker = _ThumbWorker(
                local_path_for_thumb, clip_thumb_path, self._start, parent=self,
            )
            self._thumb_worker.ready.connect(self._set_thumb_pixmap)
            self._thumb_worker.start()
        else:
            self._thumb_label.setText("▶")
            self._thumb_label.setStyleSheet(
                "background: #0f1a2e; border-radius: 4px; color: #64ffda; font-size: 18px;"
            )
        layout.addWidget(self._thumb_label)

        # Video name + time range
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        local_path = video_map.get_path(self._video_id) or ""
        vid_name = Path(local_path).name if local_path else self._video_id[:12]
        name_label = QLabel(vid_name)
        name_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #ccd6f6;")
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)

        time_range = f"{_fmt_time(self._start)} – {_fmt_time(self._end)}"
        time_label = QLabel(time_range)
        time_label.setStyleSheet("font-size: 11px; color: #8892b0;")
        info_layout.addWidget(time_label)

        layout.addLayout(info_layout, stretch=1)

        # Score
        score = result.get("score", 0.0)
        score_label = QLabel(f"{score:.1f}%")
        color = _score_color(score)
        score_label.setStyleSheet(f"font-size: 12px; color: {color}; font-weight: bold;")
        score_label.setFixedWidth(50)
        score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(score_label, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _set_thumb_pixmap(self, path: str):
        pix = QPixmap(path).scaled(
            80, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_label.setPixmap(pix)
        self._thumb_label.setStyleSheet("background: #0f1a2e; border-radius: 4px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_clicked.emit(self._video_id, self._start, self._end)
        super().mousePressEvent(event)
