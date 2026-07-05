from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from config import APP_BASE_DIR, DEFAULT_LOCALE, DEFAULT_TIMEZONE
from utils.geo_options import (
    combo_value,
    country_to_locale,
    locale_label,
    populate_locale_combo,
    populate_timezone_combo,
    set_combo_value,
    timezone_label,
)
from utils.proxy_parser import normalize_proxy
from utils.startup_url import normalize_startup_url


class ProfileDialog(QDialog):
    def __init__(
        self,
        parent=None,
        profile=None,
        proxies=None,
        default_startup_url: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit profile" if profile else "Create profile")
        self.setModal(True)
        self.resize(680, 700)
        self.setMinimumSize(620, 640)
        self.proxies = proxies or []
        self.proxy_by_url = {proxy.url: proxy for proxy in self.proxies}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(26, 24, 26, 22)
        root_layout.setSpacing(18)

        title = QLabel("Edit profile" if profile else "Create new profile")
        title.setObjectName("dialogTitle")
        root_layout.addWidget(title)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_layout.setHorizontalSpacing(22)
        form_layout.setVerticalSpacing(14)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Example: Facebook-US-01")
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://user:password@host:port")
        self.saved_proxy_input = QComboBox()
        self.saved_proxy_input.addItem("Do not use a saved proxy", "")
        for saved_proxy in self.proxies:
            self.saved_proxy_input.addItem(f"{saved_proxy.name} · {saved_proxy.location or saved_proxy.proxy_type}", saved_proxy.url)
        self.saved_proxy_input.currentIndexChanged.connect(self._apply_saved_proxy)
        self.timezone_input = QComboBox()
        populate_timezone_combo(self.timezone_input, DEFAULT_TIMEZONE)
        self.locale_input = QComboBox()
        populate_locale_combo(self.locale_input, DEFAULT_LOCALE)
        self.startup_url_input = QLineEdit()
        default_label = default_startup_url.strip() or "Blank tab"
        self.startup_url_input.setPlaceholderText(f"Leave empty to use default: {default_label}")
        self.auto_geoip_input = QCheckBox("Match timezone, locale and WebRTC to proxy")
        self.auto_geoip_input.setChecked(True)
        self.auto_geoip_input.setToolTip("Recommended when the profile uses a proxy")
        self.auto_geoip_input.toggled.connect(self._apply_selected_proxy_geo)
        self.engine_input = QComboBox()
        self.engine_input.addItem("CloakBrowser Clean 146 (recommended)", "cloak")
        self.engine_input.addItem("Google Chrome Native (Chromium)", "chrome")
        self.engine_input.currentIndexChanged.connect(self._engine_changed)
        self.platform_input = QComboBox()
        self.platform_input.addItem("Windows", "windows")
        self.platform_input.addItem("macOS", "macos")
        self.platform_input.addItem("Linux", "linux")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Example: Facebook US, customer A, Windows device...")
        self.notes_input.setMaximumHeight(78)

        self.screen_width_input = QSpinBox()
        self.screen_width_input.setRange(320, 10000)
        self.screen_width_input.setValue(1200)
        self.screen_height_input = QSpinBox()
        self.screen_height_input.setRange(320, 10000)
        self.screen_height_input.setValue(800)

        seed_layout = QHBoxLayout()
        seed_layout.setContentsMargins(0, 0, 0, 0)
        self.fingerprint_seed_input = QSpinBox()
        self.fingerprint_seed_input.setRange(100000, 999999999)
        self.fingerprint_seed_input.setValue(random.randint(100000, 999999999))
        regenerate_button = QPushButton("Regenerate")
        regenerate_button.setMinimumSize(112, 36)
        regenerate_button.clicked.connect(self.regenerate_seed)
        seed_layout.addWidget(self.fingerprint_seed_input, 1)
        seed_layout.addWidget(regenerate_button)

        for field in (
            self.name_input,
            self.proxy_input,
            self.timezone_input,
            self.locale_input,
            self.startup_url_input,
            self.saved_proxy_input,
            self.engine_input,
            self.platform_input,
            self.screen_width_input,
            self.screen_height_input,
            self.fingerprint_seed_input,
        ):
            field.setMinimumHeight(36)

        form_layout.addRow("Profile name", self.name_input)
        form_layout.addRow("Browser engine", self.engine_input)
        form_layout.addRow("Platform", self.platform_input)
        form_layout.addRow("Saved proxy", self.saved_proxy_input)
        form_layout.addRow("Proxy", self.proxy_input)
        form_layout.addRow("Timezone", self.timezone_input)
        form_layout.addRow("Language / locale", self.locale_input)
        form_layout.addRow("Startup override (optional)", self.startup_url_input)
        form_layout.addRow("Proxy sync", self.auto_geoip_input)
        form_layout.addRow("Width", self.screen_width_input)
        form_layout.addRow("Height", self.screen_height_input)
        form_layout.addRow("Fingerprint seed", seed_layout)
        form_layout.addRow("Notes", self.notes_input)

        hint = QLabel(f"Login data is stored separately at:\n{APP_BASE_DIR / 'profiles'}")
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Save profile")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        for button in buttons.buttons():
            button.setMinimumSize(100, 38)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        root_layout.addLayout(form_layout)
        root_layout.addWidget(hint)
        root_layout.addStretch(1)
        root_layout.addWidget(buttons)

        if profile:
            self.name_input.setText(profile.name)
            self.proxy_input.setText(profile.proxy or "")
            saved_index = self.saved_proxy_input.findData(profile.proxy or "")
            if saved_index >= 0:
                self.saved_proxy_input.setCurrentIndex(saved_index)
            set_combo_value(self.timezone_input, profile.timezone, timezone_label)
            set_combo_value(self.locale_input, profile.locale, locale_label)
            self.startup_url_input.setText(profile.startup_url)
            self.screen_width_input.setValue(profile.screen_width)
            self.screen_height_input.setValue(profile.screen_height)
            self.fingerprint_seed_input.setValue(profile.fingerprint_seed or random.randint(100000, 999999999))
            self.auto_geoip_input.setChecked(profile.auto_geoip)
            self.engine_input.setCurrentIndex(max(0, self.engine_input.findData(profile.browser_engine)))
            platform_index = self.platform_input.findData(profile.platform)
            self.platform_input.setCurrentIndex(max(platform_index, 0))
            self.notes_input.setPlainText(profile.notes)
        self._engine_changed()

    def _apply_saved_proxy(self) -> None:
        selected_url = self.saved_proxy_input.currentData()
        if selected_url:
            self.proxy_input.setText(selected_url)
        self._apply_selected_proxy_geo()

    def _apply_selected_proxy_geo(self, *_args) -> None:
        if not self.auto_geoip_input.isChecked():
            return
        proxy = self.proxy_by_url.get(str(self.saved_proxy_input.currentData() or ""))
        if not proxy:
            return
        if proxy.timezone:
            set_combo_value(self.timezone_input, proxy.timezone, timezone_label)
        locale = country_to_locale(proxy.country_code)
        if locale:
            set_combo_value(self.locale_input, locale, locale_label)

    def regenerate_seed(self) -> None:
        self.fingerprint_seed_input.setValue(random.randint(100000, 999999999))

    def _engine_changed(self) -> None:
        native = self.engine_input.currentData() == "chrome"
        if native:
            self.platform_input.setCurrentIndex(max(0, self.platform_input.findData("windows")))
        self.platform_input.setEnabled(not native)
        self.fingerprint_seed_input.setEnabled(not native)

    def validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Missing name", "Profile name cannot be empty.")
            return
        try:
            self.proxy_input.setText(normalize_proxy(self.proxy_input.text()) or "")
            self.startup_url_input.setText(normalize_startup_url(self.startup_url_input.text()))
        except ValueError as error:
            QMessageBox.warning(self, "Invalid proxy", str(error))
            return
        self.accept()

    def get_payload(self) -> dict[str, object]:
        return {
            "name": self.name_input.text().strip(),
            "proxy": self.proxy_input.text().strip() or None,
            "timezone": combo_value(self.timezone_input, DEFAULT_TIMEZONE),
            "locale": combo_value(self.locale_input, DEFAULT_LOCALE),
            "screen_width": int(self.screen_width_input.value()),
            "screen_height": int(self.screen_height_input.value()),
            "fingerprint_seed": int(self.fingerprint_seed_input.value()),
            "auto_geoip": self.auto_geoip_input.isChecked(),
            "platform": self.platform_input.currentData(),
            "notes": self.notes_input.toPlainText().strip(),
            "browser_engine": self.engine_input.currentData(),
            "startup_url": self.startup_url_input.text().strip(),
        }
