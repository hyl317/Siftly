from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.services.search_worker import SearchWorker
from app.widgets.search_card import SearchCard

MIN_SCORE_FOR_LEVEL = {"none": 0, "low": 1, "medium": 40, "high": 70}


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
        self.threshold_combo.setView(QListView())
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

        # Results scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(4)
        scroll.setWidget(self.results_container)
        layout.addWidget(scroll, stretch=1)

    def _search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        self._clear_results()
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
        """Filter cached results by the selected level and repopulate cards."""
        level = self.threshold_combo.currentData()
        min_score = MIN_SCORE_FOR_LEVEL.get(level, 0)
        filtered = [r for r in self._all_results if r.get("score", 0) >= min_score]

        self._clear_results()
        self.status_label.setText(f"{len(filtered)} of {len(self._all_results)} results")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

        for item_data in filtered:
            card = SearchCard(item_data, parent=self.results_container)
            card.play_clicked.connect(self._on_card_clicked)
            self.results_layout.addWidget(card)

    def _clear_results(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_error(self, msg: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def _on_card_clicked(self, video_id: str, start: float, end: float):
        self.result_clicked.emit(video_id, start, end)
