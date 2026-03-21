from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from app.config import (
    VISION_MODELS,
    get_api_key, get_anthropic_api_key, get_index_id, get_vision_model,
    set_api_key, set_anthropic_api_key, set_index_id, set_vision_model,
)
from app.services.api_client import get_client, reset_client, test_connection


class _TestWorker(QThread):
    result = Signal(bool)

    def run(self):
        self.result.emit(test_connection())


class _LoadIndexesWorker(QThread):
    result = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            client = get_client()
            indexes = client.indexes.list(page=1, page_limit=50)
            items = [{"id": idx.id, "name": idx.index_name or idx.id} for idx in indexes]
            self.result.emit(items)
        except Exception as e:
            self.error.emit(str(e))


class _CreateIndexWorker(QThread):
    result = Signal(str, str)  # id, name
    error = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.index_name = name

    def run(self):
        try:
            from twelvelabs.indexes import IndexesCreateRequestModelsItem
            client = get_client()
            index = client.indexes.create(
                index_name=self.index_name,
                models=[
                    IndexesCreateRequestModelsItem(
                        model_name="marengo3.0",
                        model_options=["visual", "audio"],
                    ),
                    IndexesCreateRequestModelsItem(
                        model_name="pegasus1.2",
                        model_options=["visual", "audio"],
                    ),
                ],
            )
            self.result.emit(index.id, self.index_name)
        except Exception as e:
            self.error.emit(str(e))


class SettingsDialog(QDialog):
    def __init__(self, parent=None, force_modal=False):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)
        if force_modal:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self._workers = []
        self._indexes = []
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # API Key section
        layout.addWidget(QLabel("Twelve Labs API Key"))
        key_row = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Enter your Twelve Labs API key")
        self.toggle_btn = QPushButton("Show")
        self.toggle_btn.setFixedWidth(70)
        self.toggle_btn.clicked.connect(self._toggle_visibility)
        key_row.addWidget(self.key_input)
        key_row.addWidget(self.toggle_btn)
        layout.addLayout(key_row)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_status = QLabel("")
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_status, stretch=1)
        layout.addLayout(test_row)

        layout.addSpacing(16)

        # Anthropic API Key section (for visual automation)
        layout.addWidget(QLabel("Anthropic API Key (for Automation)"))
        anthropic_row = QHBoxLayout()
        self.anthropic_key_input = QLineEdit()
        self.anthropic_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key_input.setPlaceholderText("Enter your Anthropic API key")
        self.anthropic_toggle_btn = QPushButton("Show")
        self.anthropic_toggle_btn.setFixedWidth(70)
        self.anthropic_toggle_btn.clicked.connect(self._toggle_anthropic_visibility)
        anthropic_row.addWidget(self.anthropic_key_input)
        anthropic_row.addWidget(self.anthropic_toggle_btn)
        layout.addLayout(anthropic_row)

        # Vision model selector
        layout.addWidget(QLabel("Vision Model"))
        self.model_combo = QComboBox()
        for model_id, label in VISION_MODELS.items():
            self.model_combo.addItem(label, model_id)
        layout.addWidget(self.model_combo)

        layout.addSpacing(16)

        # Index section
        layout.addWidget(QLabel("Index"))
        self.index_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(80)
        self.refresh_btn.clicked.connect(self._load_indexes)
        idx_row = QHBoxLayout()
        idx_row.addWidget(self.index_combo, stretch=1)
        idx_row.addWidget(self.refresh_btn)
        layout.addLayout(idx_row)

        # Create new index
        layout.addWidget(QLabel("Create New Index"))
        create_row = QHBoxLayout()
        self.new_index_input = QLineEdit()
        self.new_index_input.setPlaceholderText("New index name")
        self.create_btn = QPushButton("Create")
        self.create_btn.clicked.connect(self._create_index)
        create_row.addWidget(self.new_index_input, stretch=1)
        create_row.addWidget(self.create_btn)
        layout.addLayout(create_row)

        layout.addSpacing(16)

        # Save/Cancel
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

    def _load_current(self):
        self.key_input.setText(get_api_key())
        self.anthropic_key_input.setText(get_anthropic_api_key())
        # Select saved vision model
        current_model = get_vision_model()
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == current_model:
                self.model_combo.setCurrentIndex(i)
                break
        if get_api_key():
            self._load_indexes()

    def _toggle_visibility(self):
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_btn.setText("Hide")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_btn.setText("Show")

    def _toggle_anthropic_visibility(self):
        if self.anthropic_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.anthropic_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.anthropic_toggle_btn.setText("Hide")
        else:
            self.anthropic_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.anthropic_toggle_btn.setText("Show")

    def _test_connection(self):
        key = self.key_input.text().strip()
        if not key:
            self.test_status.setText("Enter an API key first")
            return
        set_api_key(key)
        reset_client()
        self.test_btn.setEnabled(False)
        self.test_status.setText("Testing...")

        worker = _TestWorker(self)
        worker.result.connect(self._on_test_result)
        self._workers.append(worker)
        worker.start()

    def _on_test_result(self, success: bool):
        self.test_btn.setEnabled(True)
        if success:
            self.test_status.setText("Connected!")
            self.test_status.setStyleSheet("color: #27ae60;")
            self._load_indexes()
        else:
            self.test_status.setText("Connection failed")
            self.test_status.setStyleSheet("color: #e74c3c;")

    def _load_indexes(self):
        self.index_combo.clear()
        self.index_combo.addItem("Loading...", "")
        worker = _LoadIndexesWorker(self)
        worker.result.connect(self._on_indexes_loaded)
        worker.error.connect(lambda e: self.index_combo.clear())
        self._workers.append(worker)
        worker.start()

    def _on_indexes_loaded(self, indexes: list):
        self._indexes = indexes
        self.index_combo.clear()
        current_id = get_index_id()
        select_idx = 0
        for i, idx in enumerate(indexes):
            self.index_combo.addItem(f"{idx['name']} ({idx['id'][:8]}...)", idx["id"])
            if idx["id"] == current_id:
                select_idx = i
        if indexes:
            self.index_combo.setCurrentIndex(select_idx)
        else:
            self.index_combo.addItem("No indexes found", "")

    def _create_index(self):
        name = self.new_index_input.text().strip()
        if not name:
            return
        self.create_btn.setEnabled(False)
        self.create_btn.setText("Creating...")
        worker = _CreateIndexWorker(name, self)
        worker.result.connect(self._on_index_created)
        worker.error.connect(self._on_create_error)
        self._workers.append(worker)
        worker.start()

    def _on_index_created(self, index_id: str, name: str):
        self.create_btn.setEnabled(True)
        self.create_btn.setText("Create")
        self.new_index_input.clear()
        self._load_indexes()
        set_index_id(index_id)

    def _on_create_error(self, msg: str):
        self.create_btn.setEnabled(True)
        self.create_btn.setText("Create")
        QMessageBox.warning(self, "Error", f"Failed to create index:\n{msg}")

    def _save(self):
        key = self.key_input.text().strip()
        if key:
            set_api_key(key)
            reset_client()
        anthropic_key = self.anthropic_key_input.text().strip()
        if anthropic_key:
            set_anthropic_api_key(anthropic_key)
        model_id = self.model_combo.currentData()
        if model_id:
            set_vision_model(model_id)
        idx_id = self.index_combo.currentData()
        if idx_id:
            set_index_id(idx_id)
        self.accept()
