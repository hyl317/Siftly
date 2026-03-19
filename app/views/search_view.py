from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

from pathlib import Path

from app.services.search_worker import SearchWorker
from app import video_map

MIN_SCORE_FOR_LEVEL = {"none": 0, "low": 1, "medium": 40, "high": 70}


def _score_color(score: float) -> str:
    """Return a color based on similarity score (0-100)."""
    if score >= 70:
        return "#27ae60"  # green
    elif score >= 40:
        return "#f39c12"  # orange
    else:
        return "#e74c3c"  # red


class SearchView(QWidget):
    # video_id, start_sec, end_sec
    result_clicked = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: SearchWorker | None = None
        self._all_results: list[dict] = []  # cached unfiltered results
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Search")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Search bar + threshold filter
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search across all indexed videos...")
        self.search_input.returnPressed.connect(self._search)

        self.threshold_combo = QComboBox()
        self.threshold_combo.addItem("All results", "none")
        self.threshold_combo.addItem("Low+", "low")
        self.threshold_combo.addItem("Medium+", "medium")
        self.threshold_combo.addItem("High only", "high")
        self.threshold_combo.setFixedWidth(110)
        self.threshold_combo.setToolTip("Minimum relevance level")
        self.threshold_combo.currentIndexChanged.connect(self._apply_filter)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._search)

        search_row.addWidget(self.search_input, stretch=1)
        search_row.addWidget(self.threshold_combo)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.status_label)

        # Results
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["Video", "Start", "End", "Relevance  \u24d8"])
        self.results_tree.setRootIsDecorated(False)
        self.results_tree.setAlternatingRowColors(True)
        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setToolTip("")
        self.results_tree.headerItem().setToolTip(3, (
            "Scores are normalized — the best match always gets 100%.\n"
            "A high score means strong relative match, not absolute relevance."
        ))
        self.results_tree.setColumnWidth(1, 90)
        self.results_tree.setColumnWidth(2, 90)
        self.results_tree.setColumnWidth(3, 110)
        self.results_tree.itemClicked.connect(self._on_item_clicked)
        self.results_tree.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.results_tree)

    def _search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        self.results_tree.clear()
        self._all_results.clear()

        self._worker = SearchWorker(query, parent=self)
        self._worker.results.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_results(self, items: list):
        self.search_btn.setEnabled(True)
        self._all_results = items
        self._apply_filter()

    def _apply_filter(self):
        """Filter cached results by the selected level and repopulate the tree."""
        level = self.threshold_combo.currentData()
        min_score = MIN_SCORE_FOR_LEVEL.get(level, 0)
        filtered = [r for r in self._all_results if r.get("score", 0) >= min_score]

        self.results_tree.clear()
        self.status_label.setText(f"{len(filtered)} of {len(self._all_results)} results")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

        path_map = video_map.get_all()

        for item_data in filtered:
            item = QTreeWidgetItem()
            vid = str(item_data.get("video_id", ""))
            start = item_data.get("start") or 0.0
            end = item_data.get("end") or 0.0
            score = item_data.get("score", 0.0)

            local_path = path_map.get(vid, "")
            if local_path:
                item.setText(0, Path(local_path).name)
            else:
                item.setText(0, vid)
            item.setText(1, self._fmt_time(start))
            item.setText(2, self._fmt_time(end))
            item.setText(3, f"{score:.1f}%")
            item.setData(0, Qt.ItemDataRole.UserRole, vid)
            item.setData(1, Qt.ItemDataRole.UserRole, start)
            item.setData(2, Qt.ItemDataRole.UserRole, end)

            item.setForeground(3, QColor(_score_color(score)))
            self.results_tree.addTopLevelItem(item)

    def _on_error(self, msg: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        video_id = item.data(0, Qt.ItemDataRole.UserRole)
        start = item.data(1, Qt.ItemDataRole.UserRole) or 0.0
        end = item.data(2, Qt.ItemDataRole.UserRole) or 0.0
        if video_id:
            self.result_clicked.emit(video_id, start, end)

    @staticmethod
    def _fmt_time(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m}:{s:02d}"
