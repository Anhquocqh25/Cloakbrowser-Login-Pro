from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class AddExtensionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = ""
        self.value = ""
        self.setObjectName("addExtensionDialog")
        self.setWindowTitle("Add extension")
        self.setModal(True)
        self.setFixedWidth(590)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(14)

        title = QLabel("Add extension")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Paste a Chrome Web Store, GitHub, direct CRX or ZIP link.")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://chromewebstore.google.com/detail/.../extension-id")
        self.url_input.setMinimumHeight(40)
        self.url_input.returnPressed.connect(self._accept_url)
        root.addWidget(self.url_input)

        url_actions = QHBoxLayout()
        url_actions.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        add_url_button = QPushButton("Download & add")
        add_url_button.setObjectName("primaryButton")
        add_url_button.clicked.connect(self._accept_url)
        url_actions.addWidget(cancel_button)
        url_actions.addWidget(add_url_button)
        root.addLayout(url_actions)

        divider = QLabel("OR")
        divider.setObjectName("dialogDivider")
        divider.setAlignment(Qt.AlignCenter)
        root.addWidget(divider)

        browse_button = QPushButton("Choose unpacked extension folder")
        browse_button.setMinimumHeight(40)
        browse_button.clicked.connect(self._choose_folder)
        root.addWidget(browse_button)

        safety = QLabel(
            "Only add extensions you trust. Downloaded packages are validated and loaded unpacked for every profile."
        )
        safety.setObjectName("hintLabel")
        safety.setWordWrap(True)
        root.addWidget(safety)

    def _accept_url(self) -> None:
        url = self.url_input.text().strip()
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "Invalid URL", "Paste a complete http:// or https:// extension URL.")
            return
        self.mode = "url"
        self.value = url
        self.accept()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select unpacked extension folder")
        if folder:
            self.mode = "folder"
            self.value = folder
            self.accept()
