from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFontMetrics, QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QVBoxLayout


class VideoThumbnail(QFrame):
    clicked = Signal(str)  # video_id or path
    delete_requested = Signal(str)  # video_id
    reveal_requested = Signal(str)  # video_id

    def __init__(self, identifier: str, name: str, thumbnail_path: Path | None = None,
                 file_missing: bool = False, status: str = "", duration: float = 0,
                 parent=None):
        super().__init__(parent)
        self.identifier = identifier
        self.setObjectName("videoThumbnail")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(200, 170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(188, 106)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background: #2a2a2a; border-radius: 4px;")

        if thumbnail_path and Path(thumbnail_path).exists():
            pixmap = QPixmap(str(thumbnail_path))
            scaled = pixmap.scaled(188, 106, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            if file_missing:
                scaled = self._draw_missing_badge(scaled)
            if duration > 0:
                scaled = self._draw_duration_badge(scaled, duration)
            self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("No Preview")
            self.thumb_label.setStyleSheet(
                "background: #2a2a2a; border-radius: 4px; color: #888; font-size: 11px;"
            )

        self._full_name = name
        self.name_label = QLabel()
        self.name_label.setMaximumHeight(16)
        self.name_label.setStyleSheet("font-size: 12px;")
        self.name_label.setToolTip(name)
        self._elide_name()

        layout.addWidget(self.thumb_label)
        layout.addWidget(self.name_label)

        if status:
            self.status_label = QLabel(status)
            self.status_label.setStyleSheet("font-size: 10px; color: #888;")
            layout.addWidget(self.status_label)

    def _elide_name(self):
        metrics = QFontMetrics(self.name_label.font())
        elided = metrics.elidedText(self._full_name, Qt.TextElideMode.ElideRight, 176)
        self.name_label.setText(elided)

    @staticmethod
    def _draw_missing_badge(pixmap: QPixmap) -> QPixmap:
        """Draw a warning triangle badge on the top-right corner."""
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Badge background circle
        badge_size = 22
        x = result.width() - badge_size - 4
        y = 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(x, y, badge_size, badge_size)

        # Warning "!" text
        painter.setPen(QPen(QColor("white")))
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x, y, badge_size, badge_size,
                         Qt.AlignmentFlag.AlignCenter, "!")

        painter.end()
        return result

    @staticmethod
    def _draw_duration_badge(pixmap: QPixmap, duration: float) -> QPixmap:
        """Draw a duration label on the bottom-right corner."""
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text)
        pad_x, pad_y = 4, 2
        rect_w = text_width + pad_x * 2
        rect_h = fm.height() + pad_y * 2
        x = result.width() - rect_w - 4
        y = result.height() - rect_h - 4

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(x, y, rect_w, rect_h, 3, 3)

        painter.setPen(QPen(QColor("white")))
        painter.drawText(x + pad_x, y + pad_y + fm.ascent(), text)

        painter.end()
        return result

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.identifier)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        reveal_action = menu.addAction("Reveal in Finder")
        reveal_action.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_DirOpenIcon
        ))
        menu.addSeparator()
        delete_action = menu.addAction("Delete from index")
        delete_action.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_TrashIcon
        ))
        action = menu.exec(event.globalPos())
        if action == reveal_action:
            self.reveal_requested.emit(self.identifier)
        elif action == delete_action:
            self.delete_requested.emit(self.identifier)
