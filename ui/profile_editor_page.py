from __future__ import annotations

import random

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from config import DEFAULT_LOCALE, DEFAULT_TIMEZONE
from models.bookmark import BookmarkRecord
from models.extension import ExtensionRecord
from models.profile import Profile
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
from utils.proxy_parser import normalize_proxy, parse_proxy
from utils.startup_url import normalize_startup_url


class ProfileEditorPage(QWidget):
    save_requested = Signal(str, dict)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("profileEditorPage")
        self.profile: Profile | None = None
        self.proxies: list[ProxyRecord] = []
        self.extensions: list[ExtensionRecord] = []
        self.bookmarks: list[BookmarkRecord] = []
        self.default_startup_url = ""
        self._build_ui()
        self._connect_live_summary()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton("‹  All profiles")
        back.setObjectName("editorBackButton")
        back.clicked.connect(self.cancel_requested)
        titles = QVBoxLayout()
        self.title = QLabel("Edit Browser Profile")
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel("Adjust browser identity, proxy and profile resources")
        self.subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        self.cancel_button = QPushButton("Cancel")
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("primaryButton")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.save_button.clicked.connect(self._submit)
        header.addWidget(back)
        header.addSpacing(8)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(self.cancel_button)
        header.addWidget(self.save_button)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        editor_card = QFrame()
        editor_card.setObjectName("profileEditorCard")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(18, 16, 18, 18)
        editor_layout.setSpacing(12)

        name_row = QHBoxLayout()
        name_label = QLabel("Browser Profile Name")
        name_label.setObjectName("editorFieldLabel")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Profile name")
        self.name_input.setMinimumHeight(38)
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_input, 1)
        editor_layout.addLayout(name_row)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("profileEditorTabs")
        self.tabs.addTab(self._overview_tab(), "Overview")
        self.tabs.addTab(self._proxy_tab(), "Proxy")
        self.tabs.addTab(self._timezone_tab(), "Timezone")
        self.tabs.addTab(self._extensions_tab(), "Extensions")
        self.tabs.addTab(self._bookmarks_tab(), "Bookmarks")
        self.tabs.addTab(self._geolocation_tab(), "Geolocation")
        self.tabs.addTab(self._advanced_tab(), "Advanced")
        editor_layout.addWidget(self.tabs, 1)
        body.addWidget(editor_card, 1)

        summary_card = QFrame()
        summary_card.setObjectName("profileSummaryCard")
        summary_card.setFixedWidth(285)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(18, 18, 18, 18)
        summary_layout.setSpacing(10)
        summary_title = QLabel("PROFILE SUMMARY")
        summary_title.setObjectName("summaryTitle")
        self.summary = QLabel()
        self.summary.setObjectName("profileSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.summary)
        summary_layout.addStretch(1)
        body.addWidget(summary_card)
        root.addLayout(body, 1)

    def _scroll_tab(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName("editorTabScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("editorTabContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 12, 12, 12)
        layout.setSpacing(14)
        scroll.setWidget(content)
        return scroll, content, layout

    def _section(self, title: str, description: str = "") -> tuple[QFrame, QFormLayout]:
        card = QFrame()
        card.setObjectName("editorSection")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(9)
        label = QLabel(title)
        label.setObjectName("editorSectionTitle")
        layout.addWidget(label)
        if description:
            hint = QLabel(description)
            hint.setObjectName("editorSectionHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(11)
        layout.addLayout(form)
        return card, form

    def _overview_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section("Browser profile", "Core identity and display settings for this profile.")
        self.engine_input = QComboBox()
        self.engine_input.addItem("CloakBrowser Clean 146 (recommended)", "cloak")
        self.engine_input.addItem("Google Chrome Native (Chromium)", "chrome")
        self.engine_note = QLabel()
        self.engine_note.setObjectName("engineModeNote")
        self.engine_note.setWordWrap(True)
        self.platform_input = QComboBox()
        self.platform_input.addItem("Windows 11", "windows")
        self.platform_input.addItem("macOS", "macos")
        self.platform_input.addItem("Linux", "linux")
        self.resolution_input = QComboBox()
        for width, height in ((1920, 1080), (1600, 900), (1536, 864), (1440, 900), (1366, 768), (1280, 800)):
            self.resolution_input.addItem(f"{width} × {height}", (width, height))
        self.resolution_input.setEditable(True)
        self.startup_url_input = QLineEdit()
        self.startup_url_input.setPlaceholderText("Leave empty to use the global default")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Account, customer, campaign or other identifying notes…")
        self.notes_input.setMaximumHeight(105)
        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("Example: Social, Work, Customer A")
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("Separate tags with commas")
        self.pinned_input = QCheckBox("Pin this profile")
        form.addRow("Browser engine", self.engine_input)
        form.addRow("", self.engine_note)
        form.addRow("Operating system", self.platform_input)
        form.addRow("Screen resolution", self.resolution_input)
        form.addRow("Startup website override", self.startup_url_input)
        form.addRow("Group", self.group_input)
        form.addRow("Tags", self.tags_input)
        form.addRow("Pinned", self.pinned_input)
        form.addRow("Notes", self.notes_input)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _proxy_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section(
            "Proxy connection",
            "Paste ip:port or ip:port:username:password. Full proxy URLs are also supported.",
        )
        self.proxy_scheme = QComboBox()
        self.proxy_scheme.addItem("HTTP", "http")
        self.proxy_scheme.addItem("HTTPS", "https")
        self.proxy_scheme.addItem("SOCKS5", "socks5")
        self.saved_proxy_input = QComboBox()
        self.saved_proxy_input.addItem("Custom / no saved proxy", "")
        self.saved_proxy_input.currentIndexChanged.connect(self._apply_saved_proxy)
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("127.0.0.1:8080:user:password")
        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.addWidget(self.proxy_input, 1)
        validate = QPushButton("Validate")
        validate.clicked.connect(self._validate_proxy)
        test_row.addWidget(validate)
        self.proxy_status = QLabel("Direct connection")
        self.proxy_status.setObjectName("proxyValidationStatus")
        form.addRow("Proxy type", self.proxy_scheme)
        form.addRow("Saved proxy", self.saved_proxy_input)
        form.addRow("Proxy", test_row)
        form.addRow("Status", self.proxy_status)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _timezone_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section("Language & timezone", "Manual values apply when Based on proxy is disabled.")
        self.timezone_input = QComboBox()
        populate_timezone_combo(self.timezone_input, DEFAULT_TIMEZONE)
        self.locale_input = QComboBox()
        populate_locale_combo(self.locale_input, DEFAULT_LOCALE)
        form.addRow("Timezone", self.timezone_input)
        form.addRow("Language / locale", self.locale_input)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _extensions_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section("Profile extensions", "Choose which globally enabled extensions load in this profile.")
        self.extensions_list = QListWidget()
        self.extensions_list.setObjectName("profileResourceList")
        self.extensions_list.setMinimumHeight(260)
        form.addRow(self.extensions_list)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _bookmarks_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section("Bookmark bar", "Selected bookmarks are written to this profile only.")
        self.bookmarks_list = QListWidget()
        self.bookmarks_list.setObjectName("profileResourceList")
        self.bookmarks_list.setMinimumHeight(260)
        form.addRow(self.bookmarks_list)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _geolocation_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section(
            "Geolocation consistency",
            "CloakBrowser can match timezone, locale and WebRTC behavior to the configured proxy.",
        )
        self.auto_geoip_input = QCheckBox("Based on proxy (recommended)")
        self.auto_geoip_input.setChecked(True)
        self.geo_explanation = QLabel(
            "When enabled, proxy IP data controls geolocation-related browser values. "
            "When disabled, the manual timezone and locale fields are used."
        )
        self.geo_explanation.setWordWrap(True)
        self.geo_explanation.setObjectName("editorSectionHint")
        form.addRow("Mode", self.auto_geoip_input)
        form.addRow(self.geo_explanation)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _advanced_tab(self) -> QWidget:
        scroll, _, layout = self._scroll_tab()
        card, form = self._section("Navigator", "Only settings supported by the current CloakBrowser engine are exposed.")
        self.user_agent_input = QLineEdit()
        self.user_agent_input.setPlaceholderText("Leave empty to let CloakBrowser generate a consistent User-Agent")
        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)
        self.seed_input = QSpinBox()
        self.seed_input.setRange(100000, 999999999)
        self.regenerate_seed_button = QPushButton("Regenerate")
        self.regenerate_seed_button.clicked.connect(lambda: self.seed_input.setValue(random.randint(100000, 999999999)))
        seed_row.addWidget(self.seed_input, 1)
        seed_row.addWidget(self.regenerate_seed_button)
        form.addRow("Custom User-Agent", self.user_agent_input)
        form.addRow("Fingerprint seed", seed_row)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def load_profile(
        self,
        profile: Profile,
        proxies: list[ProxyRecord],
        extensions: list[ExtensionRecord],
        bookmarks: list[BookmarkRecord],
        default_startup_url: str = "",
    ) -> None:
        self.profile = profile
        self.proxies = proxies
        self.extensions = extensions
        self.bookmarks = bookmarks
        self.default_startup_url = default_startup_url.strip()
        self.name_input.setText(profile.name)
        self.engine_input.setCurrentIndex(max(0, self.engine_input.findData(profile.browser_engine)))
        self.platform_input.setCurrentIndex(max(0, self.platform_input.findData(profile.platform)))
        resolution_index = self.resolution_input.findData((profile.screen_width, profile.screen_height))
        if resolution_index >= 0:
            self.resolution_input.setCurrentIndex(resolution_index)
        else:
            self.resolution_input.setEditText(f"{profile.screen_width} × {profile.screen_height}")
        self.notes_input.setPlainText(profile.notes)
        self.group_input.setText(profile.group_name)
        self.tags_input.setText(profile.tags)
        self.pinned_input.setChecked(profile.pinned)
        self.startup_url_input.setText(profile.startup_url)
        self.startup_url_input.setPlaceholderText(
            f"Global default: {self.default_startup_url}"
            if self.default_startup_url
            else "Global default: Blank tab"
        )
        set_combo_value(self.timezone_input, profile.timezone, timezone_label)
        set_combo_value(self.locale_input, profile.locale, locale_label)
        self.auto_geoip_input.setChecked(profile.auto_geoip)
        self.user_agent_input.setText(profile.user_agent)
        self.seed_input.setValue(profile.fingerprint_seed or random.randint(100000, 999999999))
        self.seed_input.setEnabled(not profile.seed_locked)
        self.regenerate_seed_button.setEnabled(not profile.seed_locked)
        lock_hint = "Seed Lock active · unlock it in Fingerprint Lab" if profile.seed_locked else "Fingerprint seed can be changed until it is locked"
        self.seed_input.setToolTip(lock_hint)
        self.regenerate_seed_button.setToolTip(lock_hint)

        self.saved_proxy_input.blockSignals(True)
        self.saved_proxy_input.clear()
        self.saved_proxy_input.addItem("Custom / no saved proxy", "")
        for proxy in proxies:
            self.saved_proxy_input.addItem(f"{proxy.name} · {proxy.location or proxy.proxy_type}", proxy.url)
        self.saved_proxy_input.blockSignals(False)
        saved_index = self.saved_proxy_input.findData(profile.proxy or "")
        if saved_index >= 0:
            self.saved_proxy_input.setCurrentIndex(saved_index)
        self.proxy_input.setText(profile.proxy or "")
        if profile.proxy:
            try:
                parsed = parse_proxy(profile.proxy)
                if parsed:
                    self.proxy_scheme.setCurrentIndex(max(0, self.proxy_scheme.findData(parsed.scheme)))
                    self.proxy_status.setText(f"Configured · {parsed.masked}")
            except ValueError:
                self.proxy_status.setText("Proxy needs attention")
        else:
            self.proxy_status.setText("Direct connection")

        self._fill_extensions(profile.extension_ids)
        self._fill_bookmarks(profile.bookmark_ids)
        self.tabs.setCurrentIndex(0)
        self._engine_changed()
        self._update_manual_fields()
        self._update_summary()

    def _fill_extensions(self, selected_ids: list[str] | None) -> None:
        selected = set(selected_ids) if selected_ids is not None else {item.id for item in self.extensions if item.enabled}
        self.extensions_list.clear()
        for record in self.extensions:
            item = QListWidgetItem(record.name + ("" if record.enabled else " (globally disabled)"))
            item.setData(Qt.UserRole, record.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if record.enabled and record.id in selected else Qt.Unchecked)
            if not record.enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.extensions_list.addItem(item)

    def _fill_bookmarks(self, selected_ids: list[str] | None) -> None:
        selected = set(selected_ids) if selected_ids is not None else {item.id for item in self.bookmarks}
        self.bookmarks_list.clear()
        for record in self.bookmarks:
            item = QListWidgetItem(f"{record.title}    {record.folder}")
            item.setData(Qt.UserRole, record.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if record.id in selected else Qt.Unchecked)
            self.bookmarks_list.addItem(item)

    def _checked_ids(self, widget: QListWidget) -> list[str]:
        return [
            str(widget.item(index).data(Qt.UserRole))
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.Checked
        ]

    def _apply_saved_proxy(self) -> None:
        url = self.saved_proxy_input.currentData()
        if not url:
            return
        self.proxy_input.setText(str(url))
        try:
            parsed = parse_proxy(str(url))
            if parsed:
                self.proxy_scheme.setCurrentIndex(max(0, self.proxy_scheme.findData(parsed.scheme)))
        except ValueError:
            pass
        self._apply_current_proxy_geo()
        self._validate_proxy(False)

    def _apply_current_proxy_geo(self, *_args) -> None:
        if not self.auto_geoip_input.isChecked():
            return
        url = str(self.saved_proxy_input.currentData() or "")
        proxy = next((item for item in self.proxies if item.url == url), None)
        if not proxy:
            return
        if proxy.timezone:
            set_combo_value(self.timezone_input, proxy.timezone, timezone_label)
        locale = country_to_locale(proxy.country_code)
        if locale:
            set_combo_value(self.locale_input, locale, locale_label)

    def _validate_proxy(self, show_error: bool = True) -> str | None:
        try:
            normalized = normalize_proxy(self.proxy_input.text(), self.proxy_scheme.currentData())
            self.proxy_input.setText(normalized or "")
            parsed = parse_proxy(normalized)
            self.proxy_status.setText(f"Valid · {parsed.masked}" if parsed else "Direct connection")
            self.proxy_status.setProperty("valid", "true")
            self.proxy_status.style().unpolish(self.proxy_status)
            self.proxy_status.style().polish(self.proxy_status)
            self._update_summary()
            return normalized
        except ValueError as error:
            self.proxy_status.setText(str(error))
            self.proxy_status.setProperty("valid", "false")
            self.proxy_status.style().unpolish(self.proxy_status)
            self.proxy_status.style().polish(self.proxy_status)
            if show_error:
                QMessageBox.warning(self, "Invalid proxy", str(error))
            return None

    def _resolution(self) -> tuple[int, int]:
        data = self.resolution_input.currentData()
        if isinstance(data, tuple) and len(data) == 2 and self.resolution_input.currentText() == self.resolution_input.itemText(self.resolution_input.currentIndex()):
            return int(data[0]), int(data[1])
        text = self.resolution_input.currentText().lower().replace("×", "x").replace(" ", "")
        try:
            width, height = (int(part) for part in text.split("x", 1))
        except (TypeError, ValueError):
            raise ValueError("Screen resolution must look like 1920x1080.")
        if not 320 <= width <= 10000 or not 320 <= height <= 10000:
            raise ValueError("Screen resolution is outside the supported range.")
        return width, height

    def _submit(self) -> None:
        if not self.profile:
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Missing name", "Profile name cannot be empty.")
            return
        try:
            width, height = self._resolution()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid resolution", str(error))
            return
        proxy = self._validate_proxy(bool(self.proxy_input.text().strip()))
        if self.proxy_input.text().strip() and proxy is None:
            return
        try:
            startup_url = normalize_startup_url(self.startup_url_input.text())
        except ValueError as error:
            QMessageBox.warning(self, "Invalid startup website", str(error))
            return
        self.startup_url_input.setText(startup_url)
        payload = {
            "name": self.name_input.text().strip(),
            "proxy": proxy,
            "timezone": combo_value(self.timezone_input, DEFAULT_TIMEZONE),
            "locale": combo_value(self.locale_input, DEFAULT_LOCALE),
            "screen_width": width,
            "screen_height": height,
            "fingerprint_seed": self.seed_input.value(),
            "auto_geoip": self.auto_geoip_input.isChecked(),
            "platform": self.platform_input.currentData(),
            "notes": self.notes_input.toPlainText().strip(),
            "user_agent": self.user_agent_input.text().strip(),
            "extension_ids": self._checked_ids(self.extensions_list),
            "bookmark_ids": self._checked_ids(self.bookmarks_list),
            "browser_engine": self.engine_input.currentData(),
            "startup_url": startup_url,
            "group_name": self.group_input.text().strip(),
            "tags": self.tags_input.text().strip(),
            "pinned": self.pinned_input.isChecked(),
        }
        self.save_requested.emit(self.profile.id, payload)

    def _connect_live_summary(self) -> None:
        for widget, signal_name in (
            (self.name_input, "textChanged"), (self.proxy_input, "textChanged"),
            (self.timezone_input, "currentTextChanged"), (self.locale_input, "currentTextChanged"),
            (self.user_agent_input, "textChanged"), (self.notes_input, "textChanged"),
            (self.startup_url_input, "textChanged"),
            (self.group_input, "textChanged"), (self.tags_input, "textChanged"),
            (self.platform_input, "currentIndexChanged"), (self.resolution_input, "currentTextChanged"),
            (self.engine_input, "currentIndexChanged"),
            (self.auto_geoip_input, "toggled"), (self.seed_input, "valueChanged"),
            (self.pinned_input, "toggled"),
        ):
            getattr(widget, signal_name).connect(self._update_summary)
        self.auto_geoip_input.toggled.connect(self._update_manual_fields)
        self.auto_geoip_input.toggled.connect(self._apply_current_proxy_geo)
        self.engine_input.currentIndexChanged.connect(self._engine_changed)
        self.extensions_list.itemChanged.connect(self._update_summary)
        self.bookmarks_list.itemChanged.connect(self._update_summary)

    def _update_manual_fields(self) -> None:
        manual = not self.auto_geoip_input.isChecked()
        self.timezone_input.setEnabled(manual)
        self.locale_input.setEnabled(manual)

    def _engine_changed(self, *_args) -> None:
        native = self.engine_input.currentData() == "chrome"
        if native:
            self.platform_input.setCurrentIndex(max(0, self.platform_input.findData("windows")))
            self.user_agent_input.clear()
            self.engine_note.setText(
                "Runs installed Google Chrome without Cloak fingerprint flags. "
                "No Playwright/CDP connection. "
                "Canvas/WebGL/Audio use the real machine values."
            )
        else:
            self.engine_note.setText(
                "Opens CloakBrowser directly without Playwright/CDP. Seed, Canvas, WebGL, "
                "Audio, screen, locale, timezone and proxy WebRTC identity stay profile-specific."
            )
        self.platform_input.setEnabled(not native)
        self.user_agent_input.setEnabled(not native)
        self.seed_input.setEnabled(not native)
        self._update_summary()

    def _update_summary(self, *_args) -> None:
        if not hasattr(self, "summary"):
            return
        platform = self.platform_input.currentText()
        proxy = "Direct connection"
        try:
            parsed = parse_proxy(self.proxy_input.text(), self.proxy_scheme.currentData())
            if parsed:
                proxy = parsed.masked
        except ValueError:
            proxy = "Invalid / incomplete"
        extensions = self._checked_ids(self.extensions_list) if hasattr(self, "extensions_list") else []
        bookmarks = self._checked_ids(self.bookmarks_list) if hasattr(self, "bookmarks_list") else []
        timezone = "Based on proxy" if self.auto_geoip_input.isChecked() else combo_value(self.timezone_input, DEFAULT_TIMEZONE)
        ua = "Generated by CloakBrowser" if not self.user_agent_input.text().strip() else "Custom"
        lines = (
            ("Profile", self.name_input.text() or "Untitled"),
            ("Engine", self.engine_input.currentText()),
            (
                "Startup",
                self.startup_url_input.text().strip()
                or (f"Global · {self.default_startup_url}" if self.default_startup_url else "Global · Blank tab"),
            ),
            ("Proxy", proxy),
            ("OS", platform),
            ("Resolution", self.resolution_input.currentText()),
            ("Timezone", timezone),
            ("Locale", "Based on proxy" if self.auto_geoip_input.isChecked() else combo_value(self.locale_input, DEFAULT_LOCALE)),
            ("User-Agent", ua),
            ("Fingerprint seed", str(self.seed_input.value())),
            ("Extensions", str(len(extensions))),
            ("Bookmarks", str(len(bookmarks))),
        )
        self.summary.setText("\n\n".join(f"{label}\n{value}" for label, value in lines))
