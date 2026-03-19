from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app.services.api_client import get_client
from app.config import get_index_id
from app.services.highlights_worker import (
    CATEGORY_QUERIES, HighlightsAnalyzeWorker, HighlightsSearchWorker,
)
from app.widgets.highlight_card import HighlightCard


class HighlightsView(QWidget):
    result_clicked = Signal(str, float, float)  # video_id, start, end

    def __init__(self, parent=None):
        super().__init__(parent)
        self._analyze_worker: HighlightsAnalyzeWorker | None = None
        self._search_worker: HighlightsSearchWorker | None = None
        self._all_video_ids: list[str] = []
        self._selected_video_ids: list[str] | None = None  # None = all
        self._setup_ui()

    # ── UI setup ──────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        # Header row: title + scope selector
        header = QHBoxLayout()
        title = QLabel("Highlights")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.scope_combo = QComboBox()
        self.scope_combo.setFixedWidth(180)
        self.scope_combo.setToolTip("Scope: which videos to analyze")
        header.addWidget(self.scope_combo)
        layout.addLayout(header)

        # Mode toggle: 3 buttons
        mode_row = QHBoxLayout()
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, label in [("auto", "Auto-detect"), ("category", "Categories"), ("search", "Custom Search")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("modeToggleBtn")
            btn.clicked.connect(lambda checked, k=key: self._set_mode(k))
            mode_row.addWidget(btn)
            self.mode_buttons[key] = btn
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Input area (stacked)
        self.input_stack = QStackedWidget()
        self.input_stack.setFixedHeight(50)

        # Auto-detect panel
        auto_panel = QWidget()
        auto_layout = QHBoxLayout(auto_panel)
        auto_layout.setContentsMargins(0, 4, 0, 4)
        self.discover_btn = QPushButton("Discover Highlights")
        self.discover_btn.clicked.connect(self._start_auto_detect)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_auto_detect)
        self.cancel_btn.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #888; font-size: 12px;")
        auto_layout.addWidget(self.discover_btn)
        auto_layout.addWidget(self.cancel_btn)
        auto_layout.addWidget(self.progress_label, stretch=1)
        self.input_stack.addWidget(auto_panel)  # index 0

        # Search panel
        search_panel = QWidget()
        search_layout = QHBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 4, 0, 4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Describe what you're looking for...")
        self.search_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_input.customContextMenuRequested.connect(
            lambda pos: self._show_edit_menu(self.search_input, pos)
        )
        self.search_input.returnPressed.connect(self._start_search)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._start_search)
        search_layout.addWidget(self.search_input, stretch=1)
        search_layout.addWidget(self.search_btn)
        self.input_stack.addWidget(search_panel)  # index 1

        # Category panel
        cat_panel = QWidget()
        cat_layout = QHBoxLayout(cat_panel)
        cat_layout.setContentsMargins(0, 4, 0, 4)
        cat_layout.setSpacing(6)
        self._category_buttons: list[QPushButton] = []
        for cat_key in CATEGORY_QUERIES:
            cat_btn = QPushButton(cat_key.capitalize())
            cat_btn.setObjectName("categoryPill")
            cat_btn.setCheckable(True)
            cat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cat_btn.clicked.connect(lambda checked, c=cat_key: self._start_category(c))
            cat_layout.addWidget(cat_btn)
            self._category_buttons.append(cat_btn)
        cat_layout.addStretch()
        self.input_stack.addWidget(cat_panel)  # index 2

        layout.addWidget(self.input_stack)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        # Export bar
        export_bar = QWidget()
        export_bar.setObjectName("exportBar")
        export_layout = QHBoxLayout(export_bar)
        export_layout.setContentsMargins(8, 4, 8, 4)

        self.select_all_cb = QCheckBox("Select All")
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        export_layout.addWidget(self.select_all_cb)

        export_layout.addSpacing(16)

        score_label = QLabel("Score ≥")
        score_label.setStyleSheet("font-size: 12px; color: #888;")
        export_layout.addWidget(score_label)

        self.score_threshold = QLineEdit()
        self.score_threshold.setPlaceholderText("%")
        self.score_threshold.setFixedWidth(50)
        self.score_threshold.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.score_threshold.customContextMenuRequested.connect(
            lambda pos: self._show_edit_menu(self.score_threshold, pos)
        )
        self.score_threshold.returnPressed.connect(self._on_select_by_score)
        export_layout.addWidget(self.score_threshold)

        score_help = QLabel("?")
        score_help.setStyleSheet(
            "font-size: 11px; color: #888; border: 1px solid #888; "
            "border-radius: 8px; padding: 0 4px; font-weight: bold;"
        )
        score_help.setFixedSize(16, 16)
        score_help.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_help.setToolTip(
            "Scores are normalized — the best match always gets 100%.\n"
            "A high score means strong relative match, not absolute relevance."
        )
        export_layout.addWidget(score_help)

        export_layout.addStretch()

        self.export_mode_combo = QComboBox()
        self.export_mode_combo.addItems(["Create DaVinci Project", "Export OTIO File"])
        self.export_mode_combo.setFixedWidth(190)
        self.export_mode_combo.activated.connect(self._on_export)
        export_layout.addWidget(self.export_mode_combo)

        self.export_count_label = QLabel("0 selected")
        self.export_count_label.setStyleSheet("font-size: 12px; color: #888;")
        export_layout.addWidget(self.export_count_label)

        layout.addWidget(export_bar)

        # Results scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(4)
        scroll.setWidget(self.results_container)
        layout.addWidget(scroll, stretch=1)

        # Default mode
        self._set_mode("auto")

    # ── Context menu ────────────────────────────────────────────────

    @staticmethod
    def _show_edit_menu(line_edit: QLineEdit, pos):
        menu = QMenu(line_edit)
        cut_action = menu.addAction("Cut")
        copy_action = menu.addAction("Copy")
        paste_action = menu.addAction("Paste")
        cut_action.setEnabled(line_edit.hasSelectedText())
        copy_action.setEnabled(line_edit.hasSelectedText())
        action = menu.exec(line_edit.mapToGlobal(pos))
        if action == cut_action:
            line_edit.cut()
        elif action == copy_action:
            line_edit.copy()
        elif action == paste_action:
            line_edit.paste()

    # ── Mode switching ────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        for key, btn in self.mode_buttons.items():
            btn.setChecked(key == mode)
        idx = {"auto": 0, "search": 1, "category": 2}.get(mode, 0)
        self.input_stack.setCurrentIndex(idx)

    # ── Scope ─────────────────────────────────────────────────────────

    def _refresh_scope(self):
        """Fetch video list and populate scope combo."""
        self.scope_combo.clear()
        try:
            client = get_client()
            index_id = get_index_id()
            if not index_id:
                return
            videos = client.indexes.videos.list(index_id=index_id, page=1, page_limit=50)
            self._all_video_ids = [v.id for v in videos if v.id]
            self.scope_combo.addItem(f"All videos ({len(self._all_video_ids)})", None)
        except Exception:
            self._all_video_ids = []
            self.scope_combo.addItem("All videos (0)", None)

    def _get_scoped_ids(self) -> list[str]:
        """Return video IDs based on current scope selection."""
        data = self.scope_combo.currentData()
        if data is not None:
            return data
        return self._all_video_ids

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_scope()

    # ── Auto-detect ───────────────────────────────────────────────────

    def _start_auto_detect(self):
        video_ids = self._get_scoped_ids()
        if not video_ids:
            self.status_label.setText("No videos available")
            return

        self._clear_results()
        self.discover_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress_label.setText("Starting...")

        self._analyze_worker = HighlightsAnalyzeWorker(video_ids, parent=self)
        self._analyze_worker.video_progress.connect(self._on_video_progress)
        self._analyze_worker.video_result.connect(self._on_video_result)
        self._analyze_worker.all_done.connect(self._on_auto_done)
        self._analyze_worker.retrying.connect(self._on_retrying)
        self._analyze_worker.start()

    def _cancel_auto_detect(self):
        if self._analyze_worker:
            self._analyze_worker.cancel()
        self.discover_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_label.setText("Cancelled")

    def _on_retrying(self, seconds_left: int):
        m, s = divmod(seconds_left, 60)
        self.progress_label.setText(f"Rate limited — retrying in {m}:{s:02d}")

    def _on_video_progress(self, current: int, total: int):
        self.progress_label.setText(f"Analyzing {current}/{total}...")

    def _on_video_result(self, video_id: str, highlights: list):
        for h in highlights:
            self._add_card(h)

    def _on_auto_done(self, all_highlights: list):
        self.discover_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        n_videos = len({h["video_id"] for h in all_highlights})
        self.status_label.setText(
            f"Found {len(all_highlights)} highlights across {n_videos} videos"
        )
        self.progress_label.setText("Done")

    # ── Custom search ─────────────────────────────────────────────────

    def _start_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        self._run_search_worker(query, category="")

    # ── Category search ───────────────────────────────────────────────

    def _start_category(self, category: str):
        # Highlight the active category pill
        for btn in self._category_buttons:
            btn.setChecked(btn.text().lower() == category)
        query = CATEGORY_QUERIES.get(category, category)
        self._run_search_worker(query, category=category)

    # ── Shared search logic ───────────────────────────────────────────

    def _run_search_worker(self, query: str, category: str):
        self._clear_results()
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")

        scoped = self._get_scoped_ids() or None
        self._search_worker = HighlightsSearchWorker(
            query, category=category, video_ids=scoped, parent=self,
        )
        self._search_worker.results.connect(self._on_search_results)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.start()

    def _on_search_results(self, items: list):
        self.search_btn.setEnabled(True)
        n_videos = len({r["video_id"] for r in items})
        self.status_label.setText(
            f"Found {len(items)} highlights across {n_videos} videos"
        )
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        for item in items:
            self._add_card(item)

    def _on_search_error(self, msg: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")

    # ── Results management ────────────────────────────────────────────

    def _clear_results(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.status_label.setText("")
        self.select_all_cb.setChecked(False)
        self._update_export_count()

    def _add_card(self, highlight: dict):
        card = HighlightCard(highlight, parent=self.results_container)
        card.play_clicked.connect(self._on_card_clicked)
        card.checkbox.stateChanged.connect(lambda _: self._update_export_count())
        self.results_layout.addWidget(card)

    def _on_card_clicked(self, video_id: str, start: float, end: float):
        self.result_clicked.emit(video_id, start, end)

    # ── Export ─────────────────────────────────────────────────────────

    def _get_cards(self) -> list[HighlightCard]:
        cards = []
        for i in range(self.results_layout.count()):
            w = self.results_layout.itemAt(i).widget()
            if isinstance(w, HighlightCard):
                cards.append(w)
        return cards

    def _update_export_count(self):
        count = sum(1 for c in self._get_cards() if c.checkbox.isChecked())
        self.export_count_label.setText(f"{count} selected")

    def _on_select_all(self, state: int):
        checked = state == Qt.CheckState.Checked.value
        for card in self._get_cards():
            card.checkbox.setChecked(checked)

    def _on_select_by_score(self):
        text = self.score_threshold.text().strip()
        try:
            threshold = float(text)
        except ValueError:
            return
        for card in self._get_cards():
            score = card.highlight_data.get("score", 0)
            card.checkbox.setChecked(score >= threshold)

    def _on_export(self):
        selected = [c.highlight_data for c in self._get_cards() if c.checkbox.isChecked()]
        if not selected:
            self.status_label.setText("No highlights selected")
            self.status_label.setStyleSheet("color: #888; font-size: 12px;")
            return
        if self.export_mode_combo.currentIndex() == 0:
            self._export_davinci(selected)
        else:
            self._export_otio(selected)

    def _export_otio(self, selected: list[dict]):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Timeline", "highlights.otio", "OpenTimelineIO (*.otio)"
        )
        if not path:
            return
        from app.services.otio_export import export_otio
        try:
            exported, skipped = export_otio(selected, path)
            msg = f"Exported {exported} clips to {path}"
            if skipped:
                msg += f" ({skipped} skipped — no local file)"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #64ffda; font-size: 12px;")
        except Exception as e:
            self.status_label.setText(f"Export failed: {e}")
            self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def _export_davinci(self, selected: list[dict]):
        from app.services.otio_export import export_otio
        from app.views.davinci_dialog import DaVinciProjectDialog
        dlg = DaVinciProjectDialog(selected, export_otio, parent=self)
        if dlg.exec() == DaVinciProjectDialog.DialogCode.Accepted:
            self.status_label.setText("DaVinci Resolve project created successfully")
            self.status_label.setStyleSheet("color: #64ffda; font-size: 12px;")
