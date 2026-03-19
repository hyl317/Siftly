from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.config import PROJECT_ROOT
from app.utils.thumbnails import extract_thumbnail
from app import video_map

THUMB_DIR = PROJECT_ROOT / ".thumbnails"

CATEGORY_COLORS = {
    "scenery": "#27ae60",
    "food": "#f39c12",
    "action": "#e74c3c",
    "people": "#3498db",
    "wildlife": "#2ecc71",
    "funny": "#e67e22",
    "emotional": "#9b59b6",
    "music": "#1abc9c",
    "travel": "#3498db",
    "other": "#7f8c8d",
}


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


class HighlightCard(QFrame):
    play_clicked = Signal(str, float, float)  # video_id, start, end

    def __init__(self, highlight: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("highlightCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)

        self.highlight_data = highlight
        self._video_id = highlight.get("video_id", "")
        self._start = highlight.get("start", 0.0)
        self._end = highlight.get("end", 0.0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Selection checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Thumbnail — extract at clip start time (async)
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

        # Title + video name + time range
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        title_text = highlight.get("title", "") or "Clip"
        title_label = QLabel(title_text)
        title_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #ccd6f6;")
        title_label.setWordWrap(True)
        info_layout.addWidget(title_label)

        # Video name + time
        local_path = video_map.get_path(self._video_id) or ""
        vid_name = Path(local_path).name if local_path else self._video_id[:12]
        time_range = f"{_fmt_time(self._start)} – {_fmt_time(self._end)}"
        sub_label = QLabel(f"{vid_name}  ·  {time_range}")
        sub_label.setStyleSheet("font-size: 11px; color: #8892b0;")
        info_layout.addWidget(sub_label)

        layout.addLayout(info_layout, stretch=1)

        # Category pill
        category = highlight.get("category", "other")
        cat_color = CATEGORY_COLORS.get(category, "#7f8c8d")
        cat_label = QLabel(category)
        cat_label.setFixedHeight(20)
        cat_label.setStyleSheet(
            f"background: {cat_color}; color: white; border-radius: 10px; "
            f"padding: 2px 8px; font-size: 10px; font-weight: bold;"
        )
        cat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cat_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Score
        score = highlight.get("score", 0)
        score_label = QLabel(f"{score:.0f}%")
        score_label.setStyleSheet("font-size: 12px; color: #64ffda; font-weight: bold;")
        score_label.setFixedWidth(36)
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
