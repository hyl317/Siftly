import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListView,
    QMessageBox, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from app.utils.video_prep import (
    BUILTIN_PROFILES, LUT_DIR, detect_log_profile, get_all_profiles, install_lut,
)

from app.utils.file_scanner import scan_folder
from app.utils.thumbnails import probe_video
from app.config import MAX_RESOLUTION_HEIGHT, MAX_FILE_SIZE_BYTES, VIDEO_EXTENSIONS


README_PATH = LUT_DIR / "README.md"


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _lut_is_available(profile_name: str) -> bool:
    profiles = get_all_profiles()
    filename = profiles.get(profile_name)
    return filename is not None and (LUT_DIR / filename).is_file()


def _build_per_row_items() -> list[str]:
    """Build per-row combo items. Called dynamically to pick up new installs."""
    items = ["None (Rec.709)"]
    for name in get_all_profiles():
        if _lut_is_available(name):
            items.append(name)
        else:
            items.append(f"{name}  (needs download)")
    items.append("Custom LUT...")
    return items


def _build_set_all_items() -> list[str]:
    return ["Auto-detect"] + _build_per_row_items()


# ── LUT association dialog ────────────────────────────────────────────

class LutAssociateDialog(QDialog):
    """Ask user to associate a .cube file with a known profile or define a custom one."""

    def __init__(self, lut_filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Associate LUT File")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>{lut_filename}</b><br><br>"
            f"Which color profile does this LUT convert from?"
        ))

        self._radios: list[tuple[QRadioButton, str]] = []

        # Show missing built-in profiles first
        for name in BUILTIN_PROFILES:
            if not _lut_is_available(name):
                radio = QRadioButton(name)
                self._radios.append((radio, name))
                layout.addWidget(radio)

        # Then available built-in profiles (user might want to replace)
        for name in BUILTIN_PROFILES:
            if _lut_is_available(name):
                radio = QRadioButton(f"{name}  (replace existing)")
                self._radios.append((radio, name))
                layout.addWidget(radio)

        # Custom option
        custom_row = QHBoxLayout()
        self._custom_radio = QRadioButton("Define custom profile:")
        self._custom_name = QLineEdit()
        self._custom_name.setPlaceholderText("e.g. BMD Film Gen5")
        self._custom_name.setEnabled(False)
        self._custom_radio.toggled.connect(self._custom_name.setEnabled)
        custom_row.addWidget(self._custom_radio)
        custom_row.addWidget(self._custom_name)
        layout.addLayout(custom_row)

        # Pre-select first missing profile if any
        if self._radios:
            self._radios[0][0].setChecked(True)
        else:
            self._custom_radio.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_profile(self) -> str | None:
        """Return the profile name to associate with, or None if cancelled."""
        if self._custom_radio.isChecked():
            name = self._custom_name.text().strip()
            return name if name else None
        for radio, name in self._radios:
            if radio.isChecked():
                return name
        return None


# ── Dialogs ───────────────────────────────────────────────────────────

def _show_missing_lut_dialog(parent: QWidget, profiles: set[str]) -> str:
    """Show dialog when detected LOG profiles have no bundled LUT.

    Returns "upload_anyway" or "provide_lut".
    """
    names = ", ".join(sorted(profiles))
    readme_url = README_PATH.as_uri()

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle("Missing LUT Files")
    msg.setTextFormat(Qt.TextFormat.RichText)
    msg.setText(
        f"<b>LOG footage detected ({names})</b> but the matching LUT "
        f"files are not bundled due to license restrictions."
    )
    msg.setInformativeText(
        f"Without a LUT, LOG footage looks flat and desaturated, which may "
        f"degrade AI search quality (object recognition, color-based queries).<br><br>"
        f"You can download the official LUT files from the manufacturer — "
        f"see <a href=\"{readme_url}\">LUT download instructions</a> for links.<br><br>"
        f"What would you like to do?"
    )

    upload_btn = msg.addButton("Upload as-is", QMessageBox.ButtonRole.AcceptRole)
    provide_btn = msg.addButton("I'll provide the LUT", QMessageBox.ButtonRole.ActionRole)
    msg.setDefaultButton(provide_btn)
    msg.exec()

    if msg.clickedButton() == provide_btn:
        return "provide_lut"
    return "upload_anyway"


def _show_needs_download_popup(parent: QWidget, profile: str) -> str | None:
    """Show popup when user selects a profile that needs download.

    Returns the installed profile name if user provided a LUT, or None.
    """
    readme_url = README_PATH.as_uri()
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle("LUT Not Bundled")
    msg.setTextFormat(Qt.TextFormat.RichText)
    msg.setText(
        f"<b>The {profile} LUT</b> is not included due to license restrictions."
    )
    msg.setInformativeText(
        f"Download the official .cube file from the manufacturer, then "
        f"click <b>Install LUT...</b> to add it.<br><br>"
        f"See <a href=\"{readme_url}\">LUT download instructions</a> for links."
    )
    install_btn = msg.addButton("Install LUT...", QMessageBox.ButtonRole.ActionRole)
    msg.addButton(QMessageBox.StandardButton.Cancel)
    msg.setDefaultButton(install_btn)
    msg.exec()

    if msg.clickedButton() == install_btn:
        return _pick_and_install_lut(parent)
    return None


def _pick_and_install_lut(parent: QWidget) -> str | None:
    """Open file picker, then association dialog. Installs the LUT.

    Returns the profile name the LUT was associated with, or None if cancelled.
    """
    lut_path, _ = QFileDialog.getOpenFileName(
        parent, "Select LUT File", "", "LUT Files (*.cube)"
    )
    if not lut_path:
        return None

    source = Path(lut_path)
    dialog = LutAssociateDialog(source.name, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    profile_name = dialog.selected_profile()
    if not profile_name:
        return None

    install_lut(source, profile_name)
    return profile_name


# ── Main widget ───────────────────────────────────────────────────────

class FolderBrowser(QWidget):
    upload_requested = Signal(list, list)  # file path strings, per-file color profiles

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_items: dict[str, QTreeWidgetItem] = {}
        self._profile_combos: dict[str, QComboBox] = {}  # path -> per-row combo
        self._detected_profiles: dict[str, str] = {}  # path -> detected profile name
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setStyleSheet("font-size: 13px; color: #888;")
        self.select_btn = QPushButton("Select Folder")
        self.select_btn.clicked.connect(self._select_folder)
        header.addWidget(self.folder_label, stretch=1)
        header.addWidget(self.select_btn)
        layout.addLayout(header)

        # Check all / Set All profile / Upload
        action_row = QHBoxLayout()
        self.check_all = QCheckBox("Select All")
        self.check_all.stateChanged.connect(self._toggle_all)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setMinimumWidth(60)
        self.clear_btn.clicked.connect(self._clear_list)

        set_all_label = QLabel("Color Profile:")
        set_all_label.setStyleSheet("font-size: 12px; color: #aaa;")
        self.set_all_combo = QComboBox()
        self.set_all_combo.setView(QListView())
        self.set_all_combo.setFixedWidth(160)
        self.set_all_combo.setToolTip(
            "Set color profile for all videos at once.\n"
            "Auto-detect uses camera metadata to pick the right LUT per file.\n"
            "Override individual videos using the per-row dropdown."
        )
        self.set_all_combo.currentTextChanged.connect(self._on_set_all_changed)

        self.upload_btn = QPushButton("Upload Selected")
        self.upload_btn.clicked.connect(self._upload_selected)
        self.upload_btn.setEnabled(False)

        action_row.addWidget(self.check_all)
        action_row.addWidget(self.clear_btn)
        action_row.addStretch()
        action_row.addWidget(set_all_label)
        action_row.addWidget(self.set_all_combo)
        action_row.addWidget(self.upload_btn)
        layout.addLayout(action_row)

        # File list with drop hint overlay
        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()

        # Page 0: drop hint
        self._drop_hint = QLabel("Drop video files here\nor use Select Folder above")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet(
            "color: #4a5568; font-size: 14px; border: 2px dashed #2a3f5f; border-radius: 8px;"
        )
        self._stack.addWidget(self._drop_hint)

        # Page 1: file tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "", "Filename", "Size", "Duration", "Resolution", "Color Profile", "Notes",
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        header_view = self.tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 100)
        self.tree.setColumnWidth(5, 160)
        self.tree.setColumnWidth(6, 160)
        self._stack.addWidget(self.tree)

        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack)

        self._refresh_set_all_combo()

    def _refresh_set_all_combo(self):
        """Rebuild the Set All combo to reflect currently available profiles."""
        self.set_all_combo.blockSignals(True)
        self.set_all_combo.clear()
        self.set_all_combo.addItems(_build_set_all_items())
        self.set_all_combo.blockSignals(False)

    def _refresh_all_row_combos(self):
        """Rebuild every per-row combo to reflect newly installed LUTs."""
        items = _build_per_row_items()
        for path_str, combo in self._profile_combos.items():
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            # Restore selection
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                # Profile was "(needs download)" but is now available
                clean = current.replace("  (needs download)", "")
                idx = combo.findText(clean)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    # ── Row creation ──────────────────────────────────────────────────

    def _make_profile_combo(self, video_path: Path) -> QComboBox:
        """Create a per-row profile combo, pre-selecting the auto-detected profile."""
        combo = QComboBox()
        combo.setView(QListView())
        combo.addItems(_build_per_row_items())

        detected = detect_log_profile(video_path)
        path_str = str(video_path)

        if detected:
            self._detected_profiles[path_str] = detected
            idx = combo.findText(detected)
            if idx < 0:
                idx = combo.findText(f"{detected}  (needs download)")
            if idx >= 0:
                combo.setCurrentIndex(idx)

        combo.currentTextChanged.connect(
            lambda text, p=path_str: self._on_row_profile_changed(p, text)
        )
        return combo

    def _add_tree_item(self, vpath: Path, checked: bool = False):
        """Add a single video to the tree. Returns the item or None if duplicate."""
        if str(vpath) in self._video_items:
            return None

        info = probe_video(vpath)
        size = vpath.stat().st_size
        res_str = f"{info['width']}x{info['height']}" if info["width"] else "?"

        notes = []
        if info["height"] > MAX_RESOLUTION_HEIGHT:
            notes.append("→ 720p")
        if size > MAX_FILE_SIZE_BYTES:
            notes.append("→ will split")

        duration = info.get("duration", 0)
        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        item = QTreeWidgetItem()
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        item.setCheckState(0, state)
        item.setText(1, vpath.name)
        item.setText(2, _human_size(size))
        item.setText(3, dur_str)
        item.setText(4, res_str)
        item.setText(6, ", ".join(notes))
        item.setData(0, Qt.ItemDataRole.UserRole, str(vpath))
        self.tree.addTopLevelItem(item)

        combo = self._make_profile_combo(vpath)
        self.tree.setItemWidget(item, 5, combo)

        self._video_items[str(vpath)] = item
        self._profile_combos[str(vpath)] = combo
        return item

    def _prompt_missing_luts(self):
        """If any files have detected LOG profiles with missing LUTs, prompt the user."""
        missing_profiles: set[str] = set()
        affected_paths: list[str] = []
        for path_str, profile in self._detected_profiles.items():
            if not _lut_is_available(profile):
                missing_profiles.add(profile)
                affected_paths.append(path_str)

        if not missing_profiles:
            return

        result = _show_missing_lut_dialog(self, missing_profiles)

        if result == "upload_anyway":
            for path_str in affected_paths:
                combo = self._profile_combos.get(path_str)
                if combo:
                    combo.setCurrentIndex(0)  # "None (Rec.709)"
        elif result == "provide_lut":
            installed = _pick_and_install_lut(self)
            if installed:
                # Refresh all combos and select the newly installed profile
                self._refresh_set_all_combo()
                self._refresh_all_row_combos()
                for path_str in affected_paths:
                    combo = self._profile_combos.get(path_str)
                    if combo:
                        idx = combo.findText(installed)
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
            else:
                # Cancelled — reset to None
                for path_str in affected_paths:
                    combo = self._profile_combos.get(path_str)
                    if combo:
                        combo.setCurrentIndex(0)

    # ── Actions ───────────────────────────────────────────────────────

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder")
        if not folder:
            return
        self.folder_label.setText(folder)
        self._scan(Path(folder))

    def _scan(self, folder: Path):
        self.tree.clear()
        self._video_items.clear()
        self._profile_combos.clear()
        self._detected_profiles.clear()
        videos = scan_folder(folder)

        for vpath in videos:
            self._add_tree_item(vpath, checked=False)

        self.upload_btn.setEnabled(len(videos) > 0)
        self._stack.setCurrentIndex(1 if videos else 0)

        self._prompt_missing_luts()

    def _clear_list(self):
        self.tree.clear()
        self._video_items.clear()
        self._profile_combos.clear()
        self._detected_profiles.clear()
        self.check_all.setChecked(False)
        self.upload_btn.setEnabled(False)
        self._stack.setCurrentIndex(0)
        self.folder_label.setText("No folder selected")

    def _toggle_all(self, state):
        check = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, check)

    # ── Profile combos ────────────────────────────────────────────────

    def _on_set_all_changed(self, text: str):
        """Global 'Set All' combo changed — apply to every row."""
        if text == "Custom LUT...":
            installed = _pick_and_install_lut(self)
            if installed:
                self._refresh_set_all_combo()
                self._refresh_all_row_combos()
                for combo in self._profile_combos.values():
                    idx = combo.findText(installed)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            self.set_all_combo.blockSignals(True)
            self.set_all_combo.setCurrentIndex(0)
            self.set_all_combo.blockSignals(False)
            return

        if text.endswith("(needs download)"):
            profile = text.replace("  (needs download)", "")
            installed = _show_needs_download_popup(self, profile)
            if installed:
                self._refresh_set_all_combo()
                self._refresh_all_row_combos()
                for combo in self._profile_combos.values():
                    idx = combo.findText(installed)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            self.set_all_combo.blockSignals(True)
            self.set_all_combo.setCurrentIndex(0)
            self.set_all_combo.blockSignals(False)
            return

        if text == "Auto-detect":
            self._detected_profiles.clear()
            for path_str, combo in self._profile_combos.items():
                detected = detect_log_profile(Path(path_str))
                if detected:
                    self._detected_profiles[path_str] = detected
                    idx = combo.findText(detected)
                    if idx < 0:
                        idx = combo.findText(f"{detected}  (needs download)")
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    else:
                        combo.setCurrentIndex(0)
                else:
                    combo.setCurrentIndex(0)
            self._prompt_missing_luts()
            return

        # Specific profile — set all rows to it
        for combo in self._profile_combos.values():
            idx = combo.findText(text)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _on_row_profile_changed(self, path_str: str, text: str):
        """Individual row combo changed."""
        if text == "Custom LUT...":
            combo = self._profile_combos.get(path_str)
            installed = _pick_and_install_lut(self)
            if installed:
                self._refresh_set_all_combo()
                self._refresh_all_row_combos()
                if combo:
                    idx = combo.findText(installed)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            else:
                if combo:
                    combo.setCurrentIndex(0)
        elif text.endswith("(needs download)"):
            profile = text.replace("  (needs download)", "")
            combo = self._profile_combos.get(path_str)
            installed = _show_needs_download_popup(self, profile)
            if installed:
                self._refresh_set_all_combo()
                self._refresh_all_row_combos()
                if combo:
                    idx = combo.findText(installed)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            elif combo:
                combo.setCurrentIndex(0)

    def _get_row_profile(self, path_str: str) -> str:
        """Resolve the profile string for a single row."""
        combo = self._profile_combos.get(path_str)
        if not combo:
            return ""
        text = combo.currentText()
        # Strip any stale suffix
        text = text.replace("  (needs download)", "").replace("  (replace existing)", "")
        return text

    # ── Upload ────────────────────────────────────────────────────────

    def _upload_selected(self):
        paths = []
        profiles = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                path_str = item.data(0, Qt.ItemDataRole.UserRole)
                paths.append(path_str)
                profiles.append(self._get_row_profile(path_str))
        if paths:
            self.upload_requested.emit(paths, profiles)

    # ── Drag and drop ──────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                paths.append(p)
            elif p.is_dir():
                paths.extend(scan_folder(p))
        if not paths:
            return
        event.acceptProposedAction()
        self._add_files(paths)

    def _add_files(self, paths: list[Path]):
        """Add individual video files to the tree, skipping duplicates."""
        for vpath in sorted(paths):
            self._add_tree_item(vpath, checked=True)

        self.upload_btn.setEnabled(self.tree.topLevelItemCount() > 0)
        self._stack.setCurrentIndex(1 if self.tree.topLevelItemCount() else 0)
        self.folder_label.setText(f"{self.tree.topLevelItemCount()} videos")

        self._prompt_missing_luts()
