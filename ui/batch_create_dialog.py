from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from config import DEFAULT_LOCALE, DEFAULT_TIMEZONE
from models.proxy import ProxyRecord
from utils.geo_options import (
    combo_value,
    country_to_locale,
    locale_label,
    populate_locale_combo,
    populate_timezone_combo,
    set_combo_value,
    timezone_label,
)
from utils.startup_url import normalize_startup_url


class BatchCreateDialog(QDialog):
    """Collect shared settings and generate uniquely numbered profile payloads."""

    def __init__(
        self,
        parent=None,
        proxies: list[ProxyRecord] | None = None,
        default_startup_url: str = "",
    ) -> None:
        super().__init__(parent)
        self.proxies = proxies or []
        self.proxy_by_url = {proxy.url: proxy for proxy in self.proxies}
        self.setObjectName("batchCreateDialog")
        self.setWindowTitle("Create profiles in batch")
        self.setModal(True)
        self.resize(570, 660)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(16)

        title = QLabel("Create profiles in batch")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Create numbered profiles with shared browser settings and unique fingerprints.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(12)

        self.prefix_input = QLineEdit("Profile")
        self.prefix_input.setPlaceholderText("Example: Facebook US")
        self.count_input = QSpinBox()
        self.count_input.setRange(1, 100)
        self.count_input.setValue(5)
        self.start_input = QSpinBox()
        self.start_input.setRange(1, 999999)
        self.start_input.setValue(1)

        self.engine_input = QComboBox()
        self.engine_input.addItem("CloakBrowser Clean 146 (recommended)", "cloak")
        self.engine_input.addItem("Google Chrome Native (Chromium)", "chrome")
        self.engine_input.currentIndexChanged.connect(self._engine_changed)

        self.platform_input = QComboBox()
        self.platform_input.addItem("Random OS", "random")
        self.platform_input.addItem("Windows 11", "windows")
        self.platform_input.addItem("macOS", "macos")
        self.platform_input.addItem("Linux", "linux")

        self.proxy_input = QComboBox()
        self.proxy_input.addItem("Direct connection", ("direct", ""))
        if self.proxies:
            self.proxy_input.addItem("Rotate through saved proxies", ("rotate", ""))
        for proxy in self.proxies:
            label = f"{proxy.name} · {proxy.location or proxy.proxy_type}"
            self.proxy_input.addItem(label, ("fixed", proxy.url))
        self.proxy_input.currentIndexChanged.connect(self._apply_proxy_geo)

        self.timezone_input = QComboBox()
        populate_timezone_combo(self.timezone_input, DEFAULT_TIMEZONE)
        self.locale_input = QComboBox()
        populate_locale_combo(self.locale_input, DEFAULT_LOCALE)
        self.startup_url_input = QLineEdit()
        default_label = default_startup_url.strip() or "Blank tab"
        self.startup_url_input.setPlaceholderText(f"Leave empty to use global default: {default_label}")
        self.screen_width_input = QSpinBox()
        self.screen_width_input.setRange(320, 10000)
        self.screen_width_input.setValue(1200)
        self.screen_height_input = QSpinBox()
        self.screen_height_input.setRange(320, 10000)
        self.screen_height_input.setValue(800)
        self.randomize_input = QCheckBox("Randomize OS/screen configuration for every profile")
        self.randomize_input.setChecked(True)
        self.randomize_input.setToolTip("Each profile always receives its own unique fingerprint seed")
        self.auto_geoip_input = QCheckBox("Match timezone, locale and WebRTC to proxy")
        self.auto_geoip_input.setChecked(True)
        self.auto_geoip_input.toggled.connect(self._apply_proxy_geo)
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Shared notes for this batch")
        self.notes_input.setMaximumHeight(70)

        for field in (
            self.prefix_input, self.count_input, self.start_input, self.platform_input,
            self.engine_input,
            self.proxy_input, self.timezone_input, self.locale_input,
            self.startup_url_input,
            self.screen_width_input, self.screen_height_input,
        ):
            field.setMinimumHeight(36)

        form.addRow("Name prefix", self.prefix_input)
        form.addRow("Quantity", self.count_input)
        form.addRow("Start number", self.start_input)
        form.addRow("Browser engine", self.engine_input)
        form.addRow("OS", self.platform_input)
        form.addRow("Proxy assignment", self.proxy_input)
        form.addRow("Timezone", self.timezone_input)
        form.addRow("Locale", self.locale_input)
        form.addRow("Startup override", self.startup_url_input)
        form.addRow("Screen width", self.screen_width_input)
        form.addRow("Screen height", self.screen_height_input)
        form.addRow("Fingerprint", self.randomize_input)
        form.addRow("Proxy sync", self.auto_geoip_input)
        form.addRow("Notes", self.notes_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setObjectName("hintLabel")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        self.prefix_input.textChanged.connect(self._update_preview)
        self.count_input.valueChanged.connect(self._update_preview)
        self.start_input.valueChanged.connect(self._update_preview)
        self._update_preview()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Create batch")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _engine_changed(self) -> None:
        native = self.engine_input.currentData() == "chrome"
        if native:
            self.platform_input.setCurrentIndex(max(0, self.platform_input.findData("windows")))
        self.platform_input.setEnabled(not native)

    def _apply_proxy_geo(self, *_args) -> None:
        if not self.auto_geoip_input.isChecked():
            return
        mode, fixed_proxy = self.proxy_input.currentData()
        proxy = None
        if mode == "fixed":
            proxy = self.proxy_by_url.get(str(fixed_proxy or ""))
        elif mode == "rotate" and self.proxies:
            proxy = next((item for item in self.proxies if item.timezone or item.country_code), self.proxies[0])
        if not proxy:
            return
        if proxy.timezone:
            set_combo_value(self.timezone_input, proxy.timezone, timezone_label)
        locale = country_to_locale(proxy.country_code)
        if locale:
            set_combo_value(self.locale_input, locale, locale_label)

    def _names(self) -> list[str]:
        prefix = self.prefix_input.text().strip()
        first = self.start_input.value()
        last = first + self.count_input.value() - 1
        digits = max(2, len(str(last)))
        return [f"{prefix} {number:0{digits}d}" for number in range(first, last + 1)]

    def _update_preview(self) -> None:
        names = self._names() if self.prefix_input.text().strip() else []
        if names:
            self.preview.setText(f"Preview: {names[0]}  →  {names[-1]}")
        else:
            self.preview.setText("Enter a name prefix to preview the generated names.")

    def _validate_and_accept(self) -> None:
        if not self.prefix_input.text().strip():
            QMessageBox.warning(self, "Missing name", "Enter a name prefix for this batch.")
            return
        try:
            self.startup_url_input.setText(normalize_startup_url(self.startup_url_input.text()))
        except ValueError as error:
            QMessageBox.warning(self, "Invalid startup website", str(error))
            return
        self.accept()

    def payloads(self) -> list[dict[str, object]]:
        mode, fixed_proxy = self.proxy_input.currentData()
        common = {
            "timezone": combo_value(self.timezone_input, DEFAULT_TIMEZONE),
            "locale": combo_value(self.locale_input, DEFAULT_LOCALE),
            "screen_width": self.screen_width_input.value(),
            "screen_height": self.screen_height_input.value(),
            "randomize": self.randomize_input.isChecked(),
            "auto_geoip": self.auto_geoip_input.isChecked(),
            "platform": self.platform_input.currentData(),
            "notes": self.notes_input.toPlainText().strip(),
            "browser_engine": self.engine_input.currentData(),
            "startup_url": self.startup_url_input.text().strip(),
        }
        payloads: list[dict[str, object]] = []
        for index, name in enumerate(self._names()):
            proxy_record = None
            if mode == "rotate" and self.proxies:
                proxy_record = self.proxies[index % len(self.proxies)]
                proxy = proxy_record.url
            elif mode == "fixed":
                proxy = fixed_proxy
                proxy_record = self.proxy_by_url.get(str(fixed_proxy or ""))
            else:
                proxy = None
            payload = {"name": name, "proxy": proxy, **common}
            if self.auto_geoip_input.isChecked() and proxy_record:
                if proxy_record.timezone:
                    payload["timezone"] = proxy_record.timezone
                locale = country_to_locale(proxy_record.country_code)
                if locale:
                    payload["locale"] = locale
            payloads.append(payload)
        return payloads
