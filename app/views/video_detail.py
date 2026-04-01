from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal, QUrl, QTimer
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QColor, QPen, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QStyleOptionSlider,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app.views.chat_widget import ChatWidget
from app.services.analysis_worker import AnalysisWorker


def _speaker_icon(muted: bool = False, size: int = 24) -> QIcon:
    """Draw a minimal speaker icon with optional sound-wave arcs."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor("#888") if muted else QColor("#ccd6f6")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)

    # Speaker cone: a trapezoid + rectangle
    cone = QPainterPath()
    cx, cy = size * 0.18, size * 0.30
    cone.moveTo(cx, cy)                          # top-left of rect
    cone.lineTo(size * 0.32, cy)                  # top-right of rect
    cone.lineTo(size * 0.52, size * 0.15)         # top of cone flare
    cone.lineTo(size * 0.52, size * 0.85)         # bottom of cone flare
    cone.lineTo(size * 0.32, size * 0.70)         # bottom-right of rect
    cone.lineTo(cx, size * 0.70)                  # bottom-left of rect
    cone.closeSubpath()
    p.drawPath(cone)

    # Sound wave arcs (only when not muted)
    if not muted:
        pen = QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        center_y = size * 0.50
        arc_x = size * 0.56
        # Small arc
        r1 = size * 0.16
        p.drawArc(int(arc_x - r1), int(center_y - r1),
                  int(r1 * 2), int(r1 * 2), -45 * 16, 90 * 16)
        # Large arc
        r2 = size * 0.28
        p.drawArc(int(arc_x - r2), int(center_y - r2),
                  int(r2 * 2), int(r2 * 2), -45 * 16, 90 * 16)
    else:
        # Muted: draw an X
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        x0 = size * 0.60
        p.drawLine(int(x0), int(size * 0.30), int(size * 0.82), int(size * 0.70))
        p.drawLine(int(x0), int(size * 0.70), int(size * 0.82), int(size * 0.30))

    p.end()
    return QIcon(pixmap)


class ClipSlider(QSlider):
    """Seek slider that can draw red clip-range markers."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._clip_start_ms: int = 0
        self._clip_end_ms: int = 0

    def set_clip_range(self, start_ms: int, end_ms: int):
        self._clip_start_ms = start_ms
        self._clip_end_ms = end_ms
        self.update()

    def clear_clip_range(self):
        self._clip_start_ms = 0
        self._clip_end_ms = 0
        self.update()

    def mousePressEvent(self, event):
        """Jump to the clicked position instead of paging."""
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt,
                QStyle.SubControl.SC_SliderGroove, self,
            )
            handle_rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt,
                QStyle.SubControl.SC_SliderHandle, self,
            )
            handle_w = handle_rect.width()
            usable = groove.width() - handle_w
            x_offset = groove.x() + handle_w // 2
            click_x = event.position().x() - x_offset
            ratio = max(0.0, min(1.0, click_x / usable)) if usable > 0 else 0
            value = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._clip_start_ms == 0 and self._clip_end_ms == 0:
            return
        if self.maximum() <= 0:
            return

        from PySide6.QtCore import QPoint

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self,
        )
        handle_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self,
        )
        handle_w = handle_rect.width()
        usable = groove.width() - handle_w
        x_offset = groove.x() + handle_w // 2

        def ms_to_x(ms: int) -> int:
            ratio = ms / self.maximum() if self.maximum() else 0
            return int(x_offset + ratio * usable)

        x1 = ms_to_x(self._clip_start_ms)
        x2 = ms_to_x(self._clip_end_ms)

        # Red range highlight bar
        bar_y = groove.center().y() - 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ef4444"))
        painter.setOpacity(0.5)
        painter.drawRect(x1, bar_y, max(x2 - x1, 2), 4)
        painter.setOpacity(1.0)

        # Triangular markers at start and end
        painter.setBrush(QColor("#ef4444"))
        painter.setPen(QPen(QColor("#ef4444"), 1))
        top_y = groove.y() - 4
        tri_h = 8
        for x in (x1, x2):
            painter.drawPolygon([
                QPoint(x - 5, top_y),
                QPoint(x + 5, top_y),
                QPoint(x, top_y + tri_h),
            ])

        painter.end()


class VideoPlayerWidget(QWidget):
    """Embedded video player with play/pause, seek, and clip markers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_seek_ms: int = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Video display
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(300)
        layout.addWidget(self.video_widget)

        # Player
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        # Controls
        controls = QHBoxLayout()
        self.play_btn = QPushButton("\u25b6")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setStyleSheet(
            "font-size: 16px; border-radius: 18px; padding: 0; text-align: center;"
        )
        self.play_btn.clicked.connect(self._toggle_play)

        self.seek_slider = ClipSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.player.setPosition)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setFixedWidth(100)
        self.time_label.setStyleSheet("font-size: 11px; color: #888;")

        self.mute_btn = QPushButton()
        self.mute_btn.setFixedSize(30, 30)
        self.mute_btn.setIcon(_speaker_icon(muted=False, size=30))
        self.mute_btn.setIconSize(QSize(30, 30))
        self.mute_btn.setStyleSheet(
            "border-radius: 15px; padding: 0; background: transparent; border: none;"
        )
        self.mute_btn.clicked.connect(self._toggle_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        controls.addWidget(self.play_btn)
        controls.addWidget(self.seek_slider, stretch=1)
        controls.addWidget(self.time_label)
        controls.addWidget(self.mute_btn)
        controls.addWidget(self.volume_slider)
        layout.addLayout(controls)

        # Signals
        self.player.durationChanged.connect(self._on_duration)
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        # Placeholder label (shown when no local file)
        self.no_video_label = QLabel("No local video file available for playback")
        self.no_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_video_label.setStyleSheet("color: #888; font-size: 13px; padding: 40px;")
        self.no_video_label.setVisible(False)
        layout.addWidget(self.no_video_label)

    def load(self, file_path: str, seek_to_sec: float = 0,
             clip_start_sec: float = 0, clip_end_sec: float = 0):
        """Load a local video file. Pass empty string to show placeholder."""
        self._pending_seek_ms = int(seek_to_sec * 1000) if seek_to_sec else 0

        # Set clip markers
        if clip_start_sec or clip_end_sec:
            self.seek_slider.set_clip_range(
                int(clip_start_sec * 1000), int(clip_end_sec * 1000)
            )
        else:
            self.seek_slider.clear_clip_range()

        if file_path and Path(file_path).exists():
            self.video_widget.setVisible(True)
            self.play_btn.setVisible(True)
            self.seek_slider.setVisible(True)
            self.time_label.setVisible(True)
            self.mute_btn.setVisible(True)
            self.volume_slider.setVisible(True)
            self.no_video_label.setVisible(False)
            self.player.setSource(QUrl.fromLocalFile(file_path))
        else:
            self.player.setSource(QUrl())
            self.video_widget.setVisible(False)
            self.play_btn.setVisible(False)
            self.seek_slider.setVisible(False)
            self.time_label.setVisible(False)
            self.mute_btn.setVisible(False)
            self.volume_slider.setVisible(False)
            self.no_video_label.setVisible(True)
            if file_path:
                self.no_video_label.setText(
                    "Local file has been moved or deleted.\n"
                    "Re-upload the video via the Upload tab to enable playback."
                )
            else:
                self.no_video_label.setText(
                    "No local video file available for playback.\n"
                    "Upload the video via the Upload tab to enable playback."
                )

    def stop(self):
        self.player.stop()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_duration(self, duration: int):
        self.seek_slider.setRange(0, duration)

    def _on_media_status(self, status):
        # Seek to clip start once media is loaded
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._pending_seek_ms:
            QTimer.singleShot(100, self._do_pending_seek)

    def _do_pending_seek(self):
        if self._pending_seek_ms:
            self.player.setPosition(self._pending_seek_ms)
            self._pending_seek_ms = 0

    def _on_position(self, position: int):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self.time_label.setText(
            f"{self._fmt(position)} / {self._fmt(self.player.duration())}"
        )

    def _on_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("\u275a\u275a")  # ❚❚
        else:
            self.play_btn.setText("\u25b6")  # ▶

    @staticmethod
    def _fmt(ms: int) -> str:
        s = ms // 1000
        m, s = divmod(s, 60)
        return f"{m}:{s:02d}"

    def _on_volume_changed(self, value: int):
        self.audio.setVolume(value / 100.0)
        self.mute_btn.setIcon(_speaker_icon(muted=(value == 0), size=30))

    def _toggle_mute(self):
        muted = not self.audio.isMuted()
        self.audio.setMuted(muted)
        self.mute_btn.setIcon(_speaker_icon(muted=muted, size=30))


class VideoDetailView(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_id = ""
        self._video_name = ""
        self._workers: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header with back button
        header = QHBoxLayout()
        self.back_btn = QPushButton("< Back")
        self.back_btn.clicked.connect(self._on_back)
        self.back_btn.setMinimumWidth(80)
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self.back_btn)
        header.addWidget(self.title_label, stretch=1)
        layout.addLayout(header)

        # Metadata
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.meta_label)

        # Video player
        self.player_widget = VideoPlayerWidget()
        layout.addWidget(self.player_widget)

        # Tabs
        self.tabs = QTabWidget()

        # Chat tab
        self.chat_widget = ChatWidget()
        self.tabs.addTab(self.chat_widget, "Chat")

        # Summary tab
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        self.summary_btn = QPushButton("Generate Summary")
        self.summary_btn.clicked.connect(self._generate_summary)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setPlaceholderText("Click 'Generate Summary' to get a summary of this video.")
        summary_layout.addWidget(self.summary_btn)
        summary_layout.addWidget(self.summary_text)
        self.tabs.addTab(summary_widget, "Summary")

        # Gist tab
        gist_widget = QWidget()
        gist_layout = QVBoxLayout(gist_widget)
        self.gist_btn = QPushButton("Generate Gist")
        self.gist_btn.clicked.connect(self._generate_gist)
        self.gist_text = QTextEdit()
        self.gist_text.setReadOnly(True)
        self.gist_text.setPlaceholderText("Click 'Generate Gist' to get title, topics, and hashtags.")
        gist_layout.addWidget(self.gist_btn)
        gist_layout.addWidget(self.gist_text)
        self.tabs.addTab(gist_widget, "Gist")

        layout.addWidget(self.tabs)

    def load_video(self, video_id: str, name: str = "", duration: float = 0,
                   created_at: str = "", local_path: str = "",
                   seek_to: float = 0, clip_start: float = 0, clip_end: float = 0):
        self._video_id = video_id
        self._video_name = name
        self.title_label.setText(name or video_id)

        meta_parts = []
        if duration:
            mins, secs = divmod(int(duration), 60)
            meta_parts.append(f"{mins}m {secs}s")
        if created_at:
            meta_parts.append(f"Indexed: {created_at}")
        meta_parts.append(f"ID: {video_id}")
        self.meta_label.setText("  |  ".join(meta_parts))

        # Load video player with optional seek and clip markers
        self.player_widget.load(local_path, seek_to, clip_start, clip_end)

        self.chat_widget.set_video_id(video_id)
        self.summary_text.clear()
        self.gist_text.clear()

    def _on_back(self):
        self.player_widget.stop()
        self.back_requested.emit()

    def _generate_summary(self):
        if not self._video_id:
            return
        self.summary_btn.setEnabled(False)
        self.summary_btn.setText("Generating...")
        self.summary_text.setPlaceholderText("")
        self.summary_text.setText("Generating summary...")

        worker = AnalysisWorker(
            self._video_id,
            "Provide a detailed summary of this video, including key topics, "
            "main points, and any notable moments. Use chapters if appropriate.",
        )
        worker.result.connect(self._on_summary)
        worker.error.connect(lambda e: self._on_summary_error(e))
        self._workers.append(worker)
        worker.start()

    def _on_summary(self, text: str):
        self.summary_text.setText(text)
        self.summary_btn.setEnabled(True)
        self.summary_btn.setText("Generate Summary")

    def _on_summary_error(self, msg: str):
        self.summary_text.setText(f"Error: {msg}")
        self.summary_btn.setEnabled(True)
        self.summary_btn.setText("Generate Summary")

    def _generate_gist(self):
        if not self._video_id:
            return
        self.gist_btn.setEnabled(False)
        self.gist_btn.setText("Generating...")
        self.gist_text.setText("Generating gist...")

        worker = AnalysisWorker(
            self._video_id,
            "Generate a title, 3-5 topics, and 5-8 hashtags for this video. "
            "Format as:\nTitle: ...\nTopics: ...\nHashtags: ...",
        )
        worker.result.connect(self._on_gist)
        worker.error.connect(lambda e: self._on_gist_error(e))
        self._workers.append(worker)
        worker.start()

    def _on_gist(self, text: str):
        self.gist_text.setText(text)
        self.gist_btn.setEnabled(True)
        self.gist_btn.setText("Generate Gist")

    def _on_gist_error(self, msg: str):
        self.gist_text.setText(f"Error: {msg}")
        self.gist_btn.setEnabled(True)
        self.gist_btn.setText("Generate Gist")
