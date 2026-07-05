from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from utils.proxy_parser import normalize_proxy, parse_proxy


class _BaseDialog(QDialog):
    def _add_buttons(self, layout: QVBoxLayout) -> None:
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Save")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        self.accept()


class ProxyDialog(_BaseDialog):
    def __init__(self, parent=None, record=None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Edit proxy" if record else "Add proxy")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel(self.windowTitle())
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(12)
        self.name_input = QLineEdit(record.name if record else "")
        self.name_input.setPlaceholderText("Proxy US 01")
        self.url_input = QLineEdit(record.url if record else "")
        self.url_input.setPlaceholderText("ip:port or ip:port:username:password")
        self.scheme_input = QComboBox()
        self.scheme_input.addItem("HTTP", "http")
        self.scheme_input.addItem("HTTPS", "https")
        self.scheme_input.addItem("SOCKS5", "socks5")
        if record:
            try:
                parsed = parse_proxy(record.url)
                if parsed:
                    self.scheme_input.setCurrentIndex(max(0, self.scheme_input.findData(parsed.scheme)))
            except ValueError:
                pass
        self.location_input = QLineEdit(record.location if record else "")
        self.location_input.setPlaceholderText("United States / Los Angeles")
        self.notes_input = QPlainTextEdit(record.notes if record else "")
        self.notes_input.setMaximumHeight(76)
        form.addRow("Name", self.name_input)
        form.addRow("Proxy type", self.scheme_input)
        form.addRow("Proxy", self.url_input)
        form.addRow("Location", self.location_input)
        form.addRow("Notes", self.notes_input)
        layout.addLayout(form)
        self._add_buttons(layout)

    def _validate(self) -> None:
        if not self.name_input.text().strip() or not self.url_input.text().strip():
            QMessageBox.warning(self, "Missing data", "Name and proxy URL are required.")
            return
        try:
            normalized = normalize_proxy(self.url_input.text(), self.scheme_input.currentData())
            self.url_input.setText(normalized or "")
        except ValueError as error:
            QMessageBox.warning(self, "Invalid proxy", str(error))
            return
        self.accept()

    def payload(self) -> dict:
        return {
            "proxy_id": self.record.id if self.record else None,
            "name": self.name_input.text().strip(),
            "url": self.url_input.text().strip(),
            "location": self.location_input.text().strip(),
            "notes": self.notes_input.toPlainText().strip(),
        }


class BookmarkDialog(_BaseDialog):
    def __init__(self, parent=None, record=None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Edit bookmark" if record else "Add bookmark")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel(self.windowTitle())
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(12)
        self.title_input = QLineEdit(record.title if record else "")
        self.title_input.setPlaceholderText("BrowserScan")
        self.url_input = QLineEdit(record.url if record else "")
        self.url_input.setPlaceholderText("https://example.com/")
        self.folder_input = QLineEdit(record.folder if record else "Fingerprint Tests")
        form.addRow("Name", self.title_input)
        form.addRow("URL", self.url_input)
        form.addRow("Folder", self.folder_input)
        layout.addLayout(form)
        self._add_buttons(layout)

    def _validate(self) -> None:
        if not self.title_input.text().strip() or not self.url_input.text().strip():
            QMessageBox.warning(self, "Missing data", "Name and URL are required.")
            return
        self.accept()

    def payload(self) -> dict:
        return {
            "bookmark_id": self.record.id if self.record else None,
            "title": self.title_input.text().strip(),
            "url": self.url_input.text().strip(),
            "folder": self.folder_input.text().strip(),
        }


class ColumnSettingsDialog(QDialog):
    def __init__(self, parent, sections, visible_keys: set[str], default_keys: set[str], required_keys: set[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Column Settings")
        self.setMinimumSize(390, 540)
        self.resize(410, 570)
        self.default_keys = default_keys
        self.required_keys = required_keys
        self.checkboxes: dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        title = QLabel("Visible columns")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Show or hide information in the Profiles table")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 6, 8, 6)
        content_layout.setSpacing(7)
        for section_title, columns in sections:
            section_label = QLabel(section_title)
            section_label.setObjectName("columnSection")
            content_layout.addWidget(section_label)
            for key, label in columns:
                checkbox = QCheckBox(label)
                checkbox.setObjectName("columnCheck")
                checkbox.setChecked(key in visible_keys or key in required_keys)
                checkbox.setEnabled(key not in required_keys)
                checkbox.setMinimumHeight(32)
                self.checkboxes[key] = checkbox
                content_layout.addWidget(checkbox)
            content_layout.addSpacing(8)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        reset = QPushButton("Default")
        reset.setObjectName("quietButton")
        reset.clicked.connect(self._reset_defaults)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Apply")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(reset)
        footer.addStretch(1)
        footer.addWidget(buttons)
        root.addLayout(footer)

    def _reset_defaults(self) -> None:
        for key, checkbox in self.checkboxes.items():
            checkbox.setChecked(key in self.default_keys or key in self.required_keys)

    def selected_columns(self) -> set[str]:
        selected = {key for key, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        return selected | self.required_keys
