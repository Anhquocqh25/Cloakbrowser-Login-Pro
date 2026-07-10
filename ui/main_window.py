from __future__ import annotations

import sys
import math
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QProcess, QSignalBlocker, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout,
    QComboBox, QFileDialog, QFormLayout, QGridLayout, QHeaderView, QLabel, QLineEdit,
    QInputDialog,
    QMainWindow, QMenu, QMessageBox, QPushButton,
    QProgressBar, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from config import APP_BASE_DIR, APP_VERSION, DEFAULT_LOCALE, DEFAULT_TIMEZONE, EXTENSION_STORAGE_DIR
from controllers.profile_controller import ProfileController
from models.bookmark import BookmarkRecord
from models.extension import ExtensionRecord
from models.profile import Profile
from models.proxy import ProxyRecord
from services.update_service import (
    AppUpdateInfo, UpdateCheckThread, UpdateDownloadThread,
    installation_mode, is_newer_version, launch_downloaded_update, update_asset,
)
from services.backup_service import create_full_backup
from storage.config_store import ConfigStore
from ui.add_extension_dialog import AddExtensionDialog
from ui.batch_create_dialog import BatchCreateDialog
from ui.column_settings_dialog import ColumnSettingsDialog
from ui.icon_factory import sidebar_icon
from ui.modern_controls import ModernComboBox
from ui.profile_table import PROFILE_COLUMNS, ProfileTable
from ui.profile_editor_page import ProfileEditorPage
from ui.task_center import TaskCenterPage
from ui.ux_dialogs import AdvancedFiltersDialog, BulkEditDialog, CommandPaletteDialog, OnboardingDialog, PresetChoiceDialog
from views.manage_dialogs import BookmarkDialog, ProxyDialog
from views.profile_dialog import ProfileDialog
from utils.startup_url import normalize_startup_url
from utils.geo_options import combo_value, populate_locale_combo, populate_timezone_combo
from utils.i18n import set_language, tr, translate_tree
from utils.flag_icon import country_flag_icon


PAGE_PROFILES = 0
PAGE_PROXIES = 1
PAGE_SETTINGS = 2
PAGE_EXTENSIONS = 3
PAGE_BOOKMARKS = 4
PAGE_STARTUP = 5
PAGE_TRASH = 6
PAGE_BACKUP = 7
PAGE_HEALTH = 8
PAGE_ACTIVITY = 9
PAGE_FINGERPRINT = 10
PAGE_EDITOR = 11
PAGE_DASHBOARD = 12
PAGE_TASKS = 13


class MainWindow(QMainWindow):
    def __init__(self, controller: ProfileController, config_store: ConfigStore | None = None) -> None:
        super().__init__()
        self.controller = controller
        self.config_store = config_store or ConfigStore()
        self.profiles: list[Profile] = []
        self.proxies: list[ProxyRecord] = []
        self.extensions: list[ExtensionRecord] = []
        self.bookmarks: list[BookmarkRecord] = []
        self._selected_profile_ids: list[str] = []
        self._allow_close = False
        self._pending_widths: dict[str, int] = {}
        self.deleted_profiles: list[Profile] = []
        self._trash_checked_ids: set[str] = set()
        self._last_trashed_ids: list[str] = []
        self._available_app_update: AppUpdateInfo | None = None
        self._downloaded_app_update: Path | None = None
        self._update_check_thread: UpdateCheckThread | None = None
        self._update_download_thread: UpdateDownloadThread | None = None
        self._installation_mode = installation_mode()
        self._install_after_download = False
        self._undo_stack: list[tuple[str, object]] = []
        self._nav_buttons: list[QPushButton] = []
        self._sidebar_collapsed = self.config_store.sidebar_collapsed()
        self._task_ids: dict[str, str] = {}
        self._auto_sidebar_applied = False
        self._last_visible_profiles: list[Profile] = []

        self.width_save_timer = QTimer(self)
        self.width_save_timer.setSingleShot(True)
        self.width_save_timer.setInterval(350)
        self.width_save_timer.timeout.connect(self._flush_column_widths)

        self.setWindowTitle("CloakBrowser Login")
        self.resize(1500, 860)
        self.setMinimumSize(1120, 680)
        self._build_ui()
        self._connect_signals()
        self._load_data()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.pages = QStackedWidget()
        self.pages.setObjectName("mainPages")
        root.addWidget(self._build_sidebar())
        self.pages.addWidget(self._build_profiles_page())       # 0
        self.pages.addWidget(self._build_proxies_page())        # 1
        self.pages.addWidget(self._build_settings_page())       # 2
        self.pages.addWidget(self._build_extensions_page())     # 3
        self.pages.addWidget(self._build_bookmarks_page())      # 4
        self.pages.addWidget(self._build_startup_page())        # 5
        self.pages.addWidget(self._build_trash_page())          # 6
        self.pages.addWidget(self._build_backup_page())         # 7
        self.pages.addWidget(self._build_health_page())         # 8
        self.pages.addWidget(self._build_activity_page())       # 9
        self.pages.addWidget(self._build_fingerprint_page())    # 10
        self.profile_editor = ProfileEditorPage()
        self.pages.addWidget(self.profile_editor)                # 11
        self.pages.addWidget(self._build_dashboard_page())       # 12
        self.task_center = TaskCenterPage()
        self.pages.addWidget(self.task_center)                    # 13
        root.addWidget(self.pages, 1)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(tr("Ready"))
        self.undo_button = QPushButton(tr("Undo"))
        self.undo_button.clicked.connect(self._undo_last_action)
        self.undo_button.hide()
        self.statusBar().addPermanentWidget(self.undo_button)
        self.pages.currentChanged.connect(self._page_changed)
        start_page = self.config_store.last_page()
        if start_page not in range(self.pages.count()) or start_page == PAGE_EDITOR:
            start_page = PAGE_DASHBOARD
        self.pages.setCurrentIndex(start_page)
        self._sync_nav_selection(start_page)
        self._set_sidebar_collapsed(self._sidebar_collapsed, persist=False)
        self.toast_label = QLabel(self)
        self.toast_label.setObjectName("toastNotification")
        self.toast_label.setWordWrap(True)
        self.toast_label.hide()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(5)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setFixedSize(38, 38)
        logo_path = Path(__file__).resolve().parent.parent / "assets" / "app_logo.png"
        if logo_path.exists():
            logo.setPixmap(QPixmap(str(logo_path)).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand = QLabel("CloakBrowser")
        brand.setObjectName("brandTitle")
        caption = QLabel("Profile Manager")
        caption.setObjectName("brandCaption")
        self.brand_labels_widget = QWidget()
        brand_labels = QVBoxLayout(self.brand_labels_widget)
        brand_labels.setContentsMargins(0, 0, 0, 0)
        brand_labels.setSpacing(1)
        brand_labels.addWidget(brand)
        brand_labels.addWidget(caption)
        brand_row.addWidget(logo)
        brand_row.addWidget(self.brand_labels_widget, 1)
        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setText("‹")
        self.sidebar_toggle.setToolTip("Collapse sidebar")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        brand_row.addWidget(self.sidebar_toggle)
        layout.addLayout(brand_row)
        layout.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        required_nav = [
            ("Dashboard", PAGE_DASHBOARD, "dashboard"),
            ("All profiles", PAGE_PROFILES, "profiles"), ("Profiles", PAGE_PROFILES, "profile"),
            ("Proxies", PAGE_PROXIES, "proxy"),
            ("Startup website", PAGE_STARTUP, "startup"),
            ("Trash", PAGE_TRASH, "trash"),
            ("Backup & Restore", PAGE_BACKUP, "backup"),
            ("Profile Health", PAGE_HEALTH, "health"),
            ("Activity Log", PAGE_ACTIVITY, "activity"),
            ("Fingerprint Lab", PAGE_FINGERPRINT, "fingerprint"),
            ("Task center", PAGE_TASKS, "tasks"),
            ("Settings", PAGE_SETTINGS, "settings"),
        ]
        for row, (label, page_index, icon) in enumerate(required_nav):
            button = self._nav_button(label, page_index, icon)
            if row == 0:
                button.setChecked(True)
            layout.addWidget(button)

        tools_label = QLabel("TOOLS")
        tools_label.setObjectName("sidebarSection")
        layout.addSpacing(16)
        layout.addWidget(tools_label)
        layout.addWidget(self._nav_button("Extensions", PAGE_EXTENSIONS, "extensions"))
        layout.addWidget(self._nav_button("Bookmarks", PAGE_BOOKMARKS, "bookmarks"))
        layout.addStretch(1)
        footer = QLabel(f"Version {APP_VERSION}")
        footer.setObjectName("sidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _nav_button(self, label: str, page_index: int, icon: str = "•") -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setMinimumHeight(40)
        button.setIcon(sidebar_icon(icon))
        button.setIconSize(QSize(19, 19))
        button.clicked.connect(partial(self.pages.setCurrentIndex, page_index))
        button.setProperty("fullLabel", label)
        button.setProperty("navIcon", icon)
        button.setProperty("pageIndex", page_index)
        self._nav_buttons.append(button)
        self.nav_group.addButton(button)
        return button

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget(); page.setObjectName("dashboardPage")
        layout = QVBoxLayout(page); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(16)
        header = QHBoxLayout(); labels = QVBoxLayout()
        title = QLabel("Dashboard"); title.setObjectName("pageTitle")
        subtitle = QLabel("Profile, proxy and fingerprint health at a glance"); subtitle.setObjectName("pageSubtitle")
        labels.addWidget(title); labels.addWidget(subtitle); header.addLayout(labels); header.addStretch(1)
        create = QPushButton("+ Create profile"); create.setObjectName("primaryButton"); create.clicked.connect(self.create_profile)
        check = QPushButton("Check all proxies"); check.clicked.connect(self.controller.check_all_proxies)
        header.addWidget(check); header.addWidget(create); layout.addLayout(header)

        cards = QGridLayout(); cards.setHorizontalSpacing(12); cards.setVerticalSpacing(12)
        self.dashboard_profiles_value = self._dashboard_card(cards, 0, "Profiles", "0", "Total browser identities")
        self.dashboard_running_value = self._dashboard_card(cards, 1, "Running", "0", "Active browser windows")
        self.dashboard_proxy_value = self._dashboard_card(cards, 2, "Proxy pool", "0/0", "Live and enabled")
        self.dashboard_health_value = self._dashboard_card(cards, 3, "Needs attention", "0", "Health or compatibility warnings")
        layout.addLayout(cards)

        quick = QFrame(); quick.setObjectName("settingsCard"); quick_layout = QHBoxLayout(quick); quick_layout.setContentsMargins(16, 14, 16, 14)
        quick_layout.addWidget(QLabel("Quick actions"))
        for label, callback in (
            ("Create batch", self.create_profiles_batch), ("Use preset", self.create_from_preset),
            ("Open profiles", partial(self.pages.setCurrentIndex, PAGE_PROFILES)),
            ("Fingerprint Lab", partial(self.pages.setCurrentIndex, PAGE_FINGERPRINT)),
        ):
            button = QPushButton(label); button.clicked.connect(callback); quick_layout.addWidget(button)
        quick_layout.addStretch(1); layout.addWidget(quick)

        recent_title = QLabel("Recently used profiles"); recent_title.setObjectName("settingTitle"); layout.addWidget(recent_title)
        self.dashboard_recent = self._data_table(["Name", "State", "Proxy", "Last used", ""])
        recent_header = self.dashboard_recent.horizontalHeader()
        recent_header.setSectionResizeMode(0, QHeaderView.Stretch); recent_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        recent_header.setSectionResizeMode(2, QHeaderView.Stretch); recent_header.setSectionResizeMode(3, QHeaderView.ResizeToContents); recent_header.setSectionResizeMode(4, QHeaderView.Fixed); self.dashboard_recent.setColumnWidth(4, 74)
        layout.addWidget(self.dashboard_recent, 1)
        return page

    @staticmethod
    def _dashboard_card(grid: QGridLayout, column: int, title: str, value: str, subtitle: str) -> QLabel:
        card = QFrame(); card.setObjectName("dashboardCard"); content = QVBoxLayout(card); content.setContentsMargins(18, 16, 18, 16); content.setSpacing(4)
        title_label = QLabel(title); title_label.setObjectName("dashboardCardTitle")
        value_label = QLabel(value); value_label.setObjectName("dashboardCardValue")
        subtitle_label = QLabel(subtitle); subtitle_label.setObjectName("dashboardCardSubtitle")
        content.addWidget(title_label); content.addWidget(value_label); content.addWidget(subtitle_label)
        grid.addWidget(card, 0, column)
        return value_label

    def _build_profiles_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("profilesPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)

        toolbar = QFrame()
        toolbar.setObjectName("profilesToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("profileSearch")
        self.search_input.setPlaceholderText("Search profiles")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(260)
        all_profiles = QPushButton("All profiles")
        all_profiles.setObjectName("filterChip")
        all_profiles.setCheckable(True)
        all_profiles.setChecked(True)
        create_button = QToolButton()
        create_button.setObjectName("createProfileMenuButton")
        create_button.setText("+ Create")
        create_button.setToolTip("Choose how to create profiles")
        create_button.setPopupMode(QToolButton.InstantPopup)
        create_button.setFixedHeight(34)
        create_button.setMinimumWidth(92)
        create_menu = QMenu(create_button)
        create_menu.addAction("Create one profile", self.create_profile)
        create_menu.addAction("Create profiles in batch", self.create_profiles_batch)
        create_menu.addAction("Create from preset", self.create_from_preset)
        create_button.setMenu(create_menu)
        more_button = QToolButton()
        more_button.setObjectName("toolbarMoreButton")
        more_button.setText("...")
        more_button.setFixedSize(34, 34)
        more_button.setPopupMode(QToolButton.InstantPopup)
        overflow = QMenu(more_button)
        overflow.addAction("Refresh profiles", self.controller.load_profiles)
        overflow.addAction("Create profiles in batch", self.create_profiles_batch)
        overflow.addAction("Save selected as preset", self.save_selected_as_preset)
        overflow.addAction("Manage profile presets", self.create_from_preset)
        overflow.addAction("Create sample profiles", self.create_sample_profiles)
        more_button.setMenu(overflow)
        self.profile_count = QLabel("0 profiles")
        self.profile_count.setObjectName("profileCount")
        self.sort_input = ModernComboBox()
        self.sort_input.setObjectName("profileSort")
        self.sort_input.setToolTip("Sort profiles")
        self.sort_input.addItem("Newest first", "created_desc")
        self.sort_input.addItem("Oldest first", "created_asc")
        self.sort_input.addItem("Name A–Z", "name_asc")
        self.sort_input.addItem("Name Z–A", "name_desc")
        self.sort_input.addItem("Status", "status")
        self.sort_input.addItem("Proxy", "proxy")
        self.sort_input.setMinimumWidth(145)
        self.sort_input.setFixedHeight(34)
        self.sort_input.setCurrentIndex(
            max(0, self.sort_input.findData(self.config_store.profile_sort()))
        )
        self.sort_input.currentIndexChanged.connect(self._sort_profiles_changed)
        columns_button = QPushButton("Columns")
        columns_button.setObjectName("columnsButton")
        columns_button.clicked.connect(self.open_column_settings)
        command_button = QPushButton("⌘")
        command_button.setToolTip("Command palette · Ctrl+K")
        command_button.setFixedWidth(38)
        command_button.clicked.connect(self.open_command_palette)

        toolbar_layout.addWidget(self.search_input)
        toolbar_layout.addWidget(all_profiles)
        toolbar_layout.addWidget(create_button)
        toolbar_layout.addWidget(more_button)
        toolbar_layout.addWidget(self.profile_count)
        toolbar_layout.addWidget(self.sort_input)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(command_button)
        toolbar_layout.addWidget(columns_button)
        layout.addWidget(toolbar)

        filters = QFrame()
        filters.setObjectName("filterBar")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 7, 12, 7)
        filter_layout.setSpacing(8)
        self.group_filter = ModernComboBox(); self.group_filter.addItem("All groups", "")
        self.group_filter.setMinimumWidth(145)
        self.status_filter = ModernComboBox()
        for label, value in (("All states", ""), ("Ready", "stopped"), ("Running", "running"), ("Needs attention", "attention")):
            self.status_filter.addItem(label, value)
        self.os_filter = ModernComboBox()
        for label, value in (("All systems", ""), ("Windows 11", "windows"), ("macOS", "macos"), ("Linux", "linux")):
            self.os_filter.addItem(label, value)
        self.quick_filter = ModernComboBox()
        self.quick_filter.setMinimumWidth(150)
        for label, value in (
            ("All quick filters", ""), ("Recently opened", "recent"),
            ("Has warning", "warning"), ("No proxy", "no_proxy"),
            ("Proxy failed", "proxy_failed"), ("Running now", "running"),
        ):
            self.quick_filter.addItem(label, value)
        self.tag_filter = ModernComboBox(); self.tag_filter.addItem("All tags", "")
        self.tag_filter.setMinimumWidth(130)
        self.density_input = ModernComboBox()
        for label, value in (("Comfortable", "comfortable"), ("Compact", "compact"), ("Wide", "wide")):
            self.density_input.addItem(label, value)
        self.density_input.setCurrentIndex(max(0, self.density_input.findData(self.config_store.profile_density())))
        self.density_input.setMinimumWidth(128)
        self.pinned_filter = QCheckBox("Pinned only")
        self.saved_view_input = ModernComboBox(); self.saved_view_input.setMinimumWidth(150)
        self.saved_view_input.currentIndexChanged.connect(self._apply_saved_view)
        self.more_filters_button = QToolButton()
        self.more_filters_button.setObjectName("profileFilterMoreButton")
        self.more_filters_button.setText("More filters")
        self.more_filters_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.more_filters_button.clicked.connect(self.open_advanced_filters)
        self.more_filters_button.setMinimumWidth(108)
        more_filters_menu = QMenu(self.more_filters_button)
        more_filters_menu.addAction("Advanced filters...", self.open_advanced_filters)
        more_filters_menu.addSeparator()
        more_filters_menu.addAction("Save current view", self.save_current_view)
        more_filters_menu.addAction("Delete selected view", self.delete_current_view)
        more_filters_menu.addSeparator()
        more_filters_menu.addAction("Set group for selection", self.bulk_set_group)
        more_filters_menu.addAction("Add tag to selection", self.bulk_add_tag)
        more_filters_menu.addAction("Clear tags from selection", self.bulk_clear_tags)
        more_filters_menu.addAction("Show group/tag summary", self.show_group_tag_summary)
        self.more_filters_button.setMenu(more_filters_menu)
        self.reset_filters_button = QPushButton("Reset")
        self.reset_filters_button.setObjectName("secondarySmallButton")
        self.reset_filters_button.clicked.connect(self.reset_profile_filters)
        self.filter_summary = QLabel("No extra filters")
        self.filter_summary.setObjectName("filterSummary")
        self.filter_summary.setWordWrap(False)
        filter_layout.addWidget(QLabel("Filter"))
        filter_layout.addWidget(self.saved_view_input)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addWidget(self.quick_filter)
        filter_layout.addWidget(self.more_filters_button)
        filter_layout.addWidget(self.reset_filters_button)
        filter_layout.addWidget(self.filter_summary, 1)
        filter_layout.addStretch(1)
        layout.addWidget(filters)

        bulk_bar = QFrame()
        bulk_bar.setObjectName("bulkActionBar")
        bulk_layout = QHBoxLayout(bulk_bar)
        bulk_layout.setContentsMargins(12, 7, 12, 7)
        bulk_layout.setSpacing(9)

        self.select_all_checkbox = QCheckBox("Select all")
        self.select_all_checkbox.setObjectName("selectAllCheckbox")
        self.select_all_checkbox.setTristate(True)
        self.selection_count = QLabel("0 selected")
        self.selection_count.setObjectName("selectionCount")
        self.bulk_open_button = QPushButton("Open selected")
        self.bulk_open_button.setObjectName("bulkOpenButton")
        self.bulk_open_button.setEnabled(False)
        self.bulk_delete_button = QPushButton("Move to Trash")
        self.bulk_delete_button.setObjectName("bulkDeleteButton")
        self.bulk_delete_button.setEnabled(False)
        self.bulk_stop_button = QPushButton("Stop selected")
        self.bulk_stop_button.setEnabled(False)
        self.bulk_health_button = QPushButton("Check selected")
        self.bulk_health_button.setEnabled(False)
        self.bulk_export_button = QPushButton("Export")
        self.bulk_export_button.setEnabled(False)
        self.bulk_edit_button = QPushButton("Bulk edit")
        self.bulk_edit_button.setEnabled(False)
        create_batch_button = QPushButton("+ Create batch")
        create_batch_button.setObjectName("primaryButton")
        close_all_button = QPushButton("Close all")
        close_all_button.clicked.connect(self.close_all_profiles)

        bulk_layout.addWidget(self.select_all_checkbox)
        bulk_layout.addWidget(self.selection_count)
        bulk_layout.addWidget(self.bulk_open_button)
        bulk_layout.addWidget(self.bulk_stop_button)
        bulk_layout.addWidget(self.bulk_health_button)
        bulk_layout.addWidget(self.bulk_export_button)
        bulk_layout.addWidget(self.bulk_delete_button)
        bulk_layout.addWidget(self.bulk_edit_button)
        bulk_layout.addWidget(close_all_button)
        bulk_layout.addStretch(1)
        bulk_layout.addWidget(create_batch_button)
        layout.addWidget(bulk_bar)

        self.profile_table = ProfileTable()
        visible = self.config_store.visible_columns(self.profile_table.default_visible_keys)
        self.profile_table.set_visible_columns(visible)
        self.profile_table.apply_column_widths(self.config_store.column_widths())
        self.profile_table.set_density(self.config_store.profile_density())
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        table_column = QVBoxLayout()
        table_column.setContentsMargins(0, 0, 0, 0)
        table_column.setSpacing(8)
        table_column.addWidget(self.profile_table, 1)
        self.empty_profiles_hint = QLabel("No profiles match this view. Try clearing filters or create a new profile.")
        self.empty_profiles_hint.setObjectName("hintLabel")
        self.empty_profiles_hint.setWordWrap(True)
        self.empty_profiles_hint.hide()
        table_column.addWidget(self.empty_profiles_hint)
        content.addLayout(table_column, 1)
        content.addWidget(self._build_profile_preview_panel())
        layout.addLayout(content, 1)

        self.select_all_checkbox.stateChanged.connect(self._toggle_all_profiles)
        self.bulk_open_button.clicked.connect(self.open_selected_profiles)
        self.bulk_stop_button.clicked.connect(self.stop_selected_profiles)
        self.bulk_health_button.clicked.connect(self.check_selected_profiles)
        self.bulk_export_button.clicked.connect(self.export_selected_profile)
        self.bulk_delete_button.clicked.connect(self.delete_selected_profiles)
        self.bulk_edit_button.clicked.connect(self.bulk_edit_selected_profiles)
        create_batch_button.clicked.connect(self.create_profiles_batch)
        self.group_filter.currentIndexChanged.connect(self._filter_profiles)
        self.status_filter.currentIndexChanged.connect(self._filter_profiles)
        self.os_filter.currentIndexChanged.connect(self._filter_profiles)
        self.quick_filter.currentIndexChanged.connect(self._filter_profiles)
        self.tag_filter.currentIndexChanged.connect(self._filter_profiles)
        self.density_input.currentIndexChanged.connect(self._profile_density_changed)
        self.pinned_filter.toggled.connect(self._filter_profiles)
        self._load_saved_views()
        return page

    def _build_profile_preview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("profilePreviewPanel")
        panel.setFixedWidth(318)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Profile preview")
        title.setObjectName("settingTitle")
        self.preview_status = QLabel("Select a profile to see details")
        self.preview_status.setObjectName("pageSubtitle")
        self.preview_status.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.preview_status)
        self.preview_fields: dict[str, QLabel] = {}
        for key, label in (
            ("name", "Name"), ("group", "Group"), ("tags", "Tags"),
            ("state", "State"), ("health", "Health"), ("proxy", "Proxy"),
            ("os", "OS"), ("locale", "Locale"), ("timezone", "Timezone"),
            ("seed", "Seed"), ("startup", "Startup"),
        ):
            row = QFrame()
            row.setObjectName("previewRow")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("previewCaption")
            value = QLabel("—")
            value.setObjectName("previewValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(caption)
            row_layout.addWidget(value)
            layout.addWidget(row)
            self.preview_fields[key] = value
        actions = QHBoxLayout()
        self.preview_run_button = QPushButton("Run")
        self.preview_run_button.setObjectName("bulkOpenButton")
        self.preview_edit_button = QPushButton("Edit")
        self.preview_health_button = QPushButton("Check")
        self.preview_run_button.clicked.connect(self.run_preview_profile)
        self.preview_edit_button.clicked.connect(self.edit_preview_profile)
        self.preview_health_button.clicked.connect(self.check_preview_profile)
        actions.addWidget(self.preview_run_button)
        actions.addWidget(self.preview_edit_button)
        actions.addWidget(self.preview_health_button)
        layout.addLayout(actions)
        layout.addStretch(1)
        return panel

    def _new_data_page(self, title: str, subtitle: str, action_text: str | None = None, action=None):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        labels = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        labels.addWidget(title_label)
        labels.addWidget(subtitle_label)
        header.addLayout(labels)
        header.addStretch(1)
        if action_text and action:
            button = QPushButton(action_text)
            button.setObjectName("primaryButton")
            button.clicked.connect(action)
            header.addWidget(button)
        layout.addLayout(header)
        return page, layout

    def _data_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("dataTable")
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(54)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setTextElideMode(Qt.ElideRight)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.horizontalHeader().setMinimumHeight(46)
        return table

    def _build_proxies_page(self) -> QWidget:
        page, layout = self._new_data_page("Proxies", "Manage reusable proxy connections", "+ Add proxy", self.add_proxy)
        proxy_bar = QFrame()
        proxy_bar.setObjectName("proxyActionBar")
        proxy_bar_layout = QHBoxLayout(proxy_bar)
        proxy_bar_layout.setContentsMargins(12, 8, 12, 8)
        proxy_bar_layout.addWidget(QLabel("Check connectivity, authentication and exit IP"))
        self.proxy_pool_enabled = QCheckBox("Smart Pool")
        self.proxy_pool_enabled.setChecked(self.config_store.proxy_pool_enabled())
        self.proxy_pool_enabled.toggled.connect(self._save_proxy_pool_settings)
        self.proxy_pool_interval = ModernComboBox()
        for label, minutes in (("5 min", 5), ("15 min", 15), ("30 min", 30), ("1 hour", 60), ("3 hours", 180)):
            self.proxy_pool_interval.addItem(label, minutes)
        self.proxy_pool_interval.setCurrentIndex(max(0, self.proxy_pool_interval.findData(self.config_store.proxy_pool_interval_minutes())))
        self.proxy_pool_interval.currentIndexChanged.connect(self._save_proxy_pool_settings)
        proxy_bar_layout.addWidget(self.proxy_pool_enabled)
        proxy_bar_layout.addWidget(self.proxy_pool_interval)
        proxy_bar_layout.addStretch(1)
        check_all_button = QPushButton("Check all proxies")
        check_all_button.setObjectName("proxyCheckButton")
        check_all_button.clicked.connect(self.controller.check_all_proxies)
        proxy_bar_layout.addWidget(check_all_button)
        layout.addWidget(proxy_bar)
        self.proxies_table = self._data_table([
            "Name", "Type", "Address", "Location", "Notes", "Status",
            "Quality", "Pool", "Exit IP / latency", "Last checked", "",
        ])
        header = self.proxies_table.horizontalHeader()
        for index in (0, 2, 3, 4, 8): header.setSectionResizeMode(index, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed); self.proxies_table.setColumnWidth(1, 100)
        for index, width in ((5, 105), (6, 90), (7, 90), (9, 145), (10, 58)):
            header.setSectionResizeMode(index, QHeaderView.Fixed); self.proxies_table.setColumnWidth(index, width)
        layout.addWidget(self.proxies_table, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page, layout = self._new_data_page("Settings", "Application and storage settings")
        card = QFrame(); card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card); card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.addWidget(QLabel(f"Version {APP_VERSION}"))
        path_label = QLabel("Profile data directory"); path_label.setObjectName("settingLabel")
        card_layout.addWidget(path_label)
        path_value = QLabel(str(APP_BASE_DIR)); path_value.setWordWrap(True); path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(path_value)
        language_label = QLabel("Interface language")
        language_label.setObjectName("settingLabel")
        card_layout.addWidget(language_label)
        language_row = QHBoxLayout()
        self.language_input = ModernComboBox()
        self.language_input.addItem("English", "en")
        self.language_input.addItem("Tiếng Việt", "vi")
        self.language_input.setCurrentIndex(
            max(0, self.language_input.findData(self.config_store.language()))
        )
        self.language_input.setMinimumHeight(38)
        apply_language = QPushButton("Apply & restart")
        apply_language.setObjectName("primaryButton")
        apply_language.clicked.connect(self._apply_interface_language)
        language_row.addWidget(self.language_input, 1)
        language_row.addWidget(apply_language)
        card_layout.addLayout(language_row)

        search_label = QLabel("Default search engine")
        search_label.setObjectName("settingLabel")
        card_layout.addWidget(search_label)
        search_value = QLabel("DuckDuckGo · applied safely to every browser profile")
        search_value.setWordWrap(True)
        card_layout.addWidget(search_value)
        experience_row = QHBoxLayout()
        welcome_button = QPushButton("Show welcome guide")
        welcome_button.clicked.connect(self.show_onboarding_again)
        shortcuts_button = QPushButton("Open command palette · Ctrl+K")
        shortcuts_button.clicked.connect(self.open_command_palette)
        experience_row.addWidget(welcome_button); experience_row.addWidget(shortcuts_button); experience_row.addStretch(1)
        card_layout.addLayout(experience_row)
        layout.addWidget(card)

        update_card = QFrame(); update_card.setObjectName("settingsCard")
        update_layout = QVBoxLayout(update_card); update_layout.setContentsMargins(20, 18, 20, 18)
        update_title = QLabel("App updates"); update_title.setObjectName("settingTitle")
        update_layout.addWidget(update_title)
        mode_text = {
            "installed": "Installed edition · updates use the Windows installer",
            "portable": "Portable edition · updates replace only application files",
            "development": "Development mode · update checks are available for testing",
        }[self._installation_mode]
        self.app_update_mode_label = QLabel(mode_text)
        self.app_update_mode_label.setObjectName("pageSubtitle")
        self.app_update_mode_label.setWordWrap(True)
        update_layout.addWidget(self.app_update_mode_label)
        self.app_update_status = QLabel(tr(f"Current version: {APP_VERSION}"))
        self.app_update_status.setWordWrap(True)
        update_layout.addWidget(self.app_update_status)
        self.app_update_asset_label = QLabel("Asset: not checked yet")
        self.app_update_asset_label.setObjectName("hintLabel")
        self.app_update_asset_label.setWordWrap(True)
        update_layout.addWidget(self.app_update_asset_label)
        self.app_update_notes = QLabel("Release notes will appear here after checking GitHub.")
        self.app_update_notes.setObjectName("pageSubtitle")
        self.app_update_notes.setWordWrap(True)
        self.app_update_notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        update_layout.addWidget(self.app_update_notes)
        self.app_update_progress = QProgressBar()
        self.app_update_progress.setRange(0, 100)
        self.app_update_progress.setTextVisible(True)
        self.app_update_progress.hide()
        update_layout.addWidget(self.app_update_progress)
        update_buttons = QHBoxLayout()
        self.check_app_update_button = QPushButton("Check for updates")
        self.check_app_update_button.clicked.connect(self.check_app_update)
        self.install_app_update_button = QPushButton("Update now")
        self.install_app_update_button.setObjectName("primaryButton")
        self.install_app_update_button.clicked.connect(self.download_or_install_app_update)
        self.install_app_update_button.hide()
        self.open_release_button = QPushButton("Open release page")
        self.open_release_button.clicked.connect(self.open_latest_release_page)
        self.open_release_button.hide()
        update_buttons.addWidget(self.check_app_update_button)
        update_buttons.addWidget(self.install_app_update_button)
        update_buttons.addWidget(self.open_release_button)
        update_buttons.addStretch(1)
        update_layout.addLayout(update_buttons)
        layout.addWidget(update_card)
        layout.addStretch(1)
        return page

    def _build_settings_section_page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("settingTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return page, layout

    def _settings_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        return card, layout

    def _build_settings_page(self) -> QWidget:
        page, layout = self._new_data_page("Settings", "Application, launch safety and profile defaults")
        shell = QFrame()
        shell.setObjectName("settingsShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(14)

        nav = QFrame()
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(185)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(6, 6, 6, 6)
        nav_layout.setSpacing(6)
        self.settings_nav_group = QButtonGroup(self)
        self.settings_nav_group.setExclusive(True)
        self.settings_stack = QStackedWidget()
        sections = [
            ("General", self._build_general_settings_section()),
            ("Profile Defaults", self._build_profile_defaults_settings_section()),
            ("Proxy", self._build_proxy_settings_section()),
            ("Fingerprint Guard", self._build_fingerprint_guard_settings_section()),
            ("Data & Backup", self._build_data_backup_settings_section()),
            ("Updates", self._build_update_settings_section()),
        ]
        for index, (label, widget) in enumerate(sections):
            button = QPushButton(label)
            button.setObjectName("settingsNavButton")
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(partial(self.settings_stack.setCurrentIndex, index))
            self.settings_nav_group.addButton(button)
            nav_layout.addWidget(button)
            self.settings_stack.addWidget(widget)
            if index == 0:
                button.setChecked(True)
        nav_layout.addStretch(1)
        shell_layout.addWidget(nav)
        shell_layout.addWidget(self.settings_stack, 1)
        layout.addWidget(shell, 1)
        return page

    def _build_general_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("General", "Language, data directory and everyday app controls.")
        card, card_layout = self._settings_card()
        card_layout.addWidget(QLabel(f"Version {APP_VERSION}"))
        path_label = QLabel("Profile data directory")
        path_label.setObjectName("settingLabel")
        card_layout.addWidget(path_label)
        path_value = QLabel(str(APP_BASE_DIR))
        path_value.setWordWrap(True)
        path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(path_value)
        language_label = QLabel("Interface language")
        language_label.setObjectName("settingLabel")
        card_layout.addWidget(language_label)
        language_row = QHBoxLayout()
        self.language_input = ModernComboBox()
        self.language_input.addItem("English", "en")
        self.language_input.addItem("Tieng Viet", "vi")
        self.language_input.setCurrentIndex(max(0, self.language_input.findData(self.config_store.language())))
        apply_language = QPushButton("Apply & restart")
        apply_language.setObjectName("primaryButton")
        apply_language.clicked.connect(self._apply_interface_language)
        language_row.addWidget(self.language_input, 1)
        language_row.addWidget(apply_language)
        card_layout.addLayout(language_row)
        search_value = QLabel("Default search engine: DuckDuckGo. Applied through browser preferences, not extension injection.")
        search_value.setWordWrap(True)
        card_layout.addWidget(search_value)
        experience_row = QHBoxLayout()
        welcome_button = QPushButton("Show welcome guide")
        welcome_button.clicked.connect(self.show_onboarding_again)
        shortcuts_button = QPushButton("Open command palette")
        shortcuts_button.clicked.connect(self.open_command_palette)
        experience_row.addWidget(welcome_button)
        experience_row.addWidget(shortcuts_button)
        experience_row.addStretch(1)
        card_layout.addLayout(experience_row)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_profile_defaults_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("Profile Defaults", "Default values used by Create profile and Create batch.")
        defaults = self.config_store.profile_defaults()
        card, card_layout = self._settings_card()
        form = QFormLayout()
        form.setSpacing(12)
        self.default_engine_input = ModernComboBox()
        self.default_engine_input.addItem("CloakBrowser Clean 146", "cloak")
        self.default_engine_input.addItem("Google Chrome Native", "chrome")
        self.default_engine_input.setCurrentIndex(max(0, self.default_engine_input.findData(str(defaults["browser_engine"]))))
        self.default_platform_input = ModernComboBox()
        for label, value in (("Windows 11", "windows"), ("macOS", "macos"), ("Linux", "linux"), ("Random for batch", "random")):
            self.default_platform_input.addItem(label, value)
        self.default_platform_input.setCurrentIndex(max(0, self.default_platform_input.findData(str(defaults["platform"]))))
        self.default_timezone_input = ModernComboBox()
        populate_timezone_combo(self.default_timezone_input, str(defaults["timezone"]))
        self.default_locale_input = ModernComboBox()
        populate_locale_combo(self.default_locale_input, str(defaults["locale"]))
        self.default_width_input = QSpinBox()
        self.default_width_input.setRange(320, 10000)
        self.default_width_input.setValue(int(defaults["screen_width"]))
        self.default_height_input = QSpinBox()
        self.default_height_input.setRange(320, 10000)
        self.default_height_input.setValue(int(defaults["screen_height"]))
        self.default_auto_geoip_input = QCheckBox("Match timezone, locale and WebRTC with proxy by default")
        self.default_auto_geoip_input.setChecked(bool(defaults["auto_geoip"]))
        self.default_group_input = QLineEdit(str(defaults.get("group_name") or ""))
        self.default_group_input.setPlaceholderText("Example: Facebook US")
        self.default_tags_input = QLineEdit(str(defaults.get("tags") or ""))
        self.default_tags_input.setPlaceholderText("Comma-separated tags")
        form.addRow("Browser engine", self.default_engine_input)
        form.addRow("OS / platform", self.default_platform_input)
        form.addRow("Timezone", self.default_timezone_input)
        form.addRow("Language / locale", self.default_locale_input)
        form.addRow("Screen width", self.default_width_input)
        form.addRow("Screen height", self.default_height_input)
        form.addRow("Proxy sync", self.default_auto_geoip_input)
        form.addRow("Default group", self.default_group_input)
        form.addRow("Default tags", self.default_tags_input)
        card_layout.addLayout(form)
        save = QPushButton("Save profile defaults")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_profile_defaults_settings)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save)
        card_layout.addLayout(row)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_proxy_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("Proxy", "Safety checks before browser profiles launch.")
        card, card_layout = self._settings_card()
        self.proxy_check_before_run_input = QCheckBox("Check assigned proxy before opening a profile")
        self.proxy_check_before_run_input.setChecked(self.config_store.proxy_check_before_run())
        self.warn_no_proxy_input = QCheckBox("Warn before opening profiles without proxy")
        self.warn_no_proxy_input.setChecked(self.config_store.warn_profiles_without_proxy())
        self.settings_proxy_pool_enabled = QCheckBox("Enable Smart Proxy Pool")
        self.settings_proxy_pool_enabled.setChecked(self.config_store.proxy_pool_enabled())
        self.settings_proxy_pool_interval = ModernComboBox()
        for label, value in (("Every 5 minutes", 5), ("Every 15 minutes", 15), ("Every 30 minutes", 30), ("Every hour", 60), ("Every 3 hours", 180)):
            self.settings_proxy_pool_interval.addItem(label, value)
        self.settings_proxy_pool_interval.setCurrentIndex(max(0, self.settings_proxy_pool_interval.findData(self.config_store.proxy_pool_interval_minutes())))
        card_layout.addWidget(self.proxy_check_before_run_input)
        card_layout.addWidget(self.warn_no_proxy_input)
        pool_row = QHBoxLayout()
        pool_row.addWidget(self.settings_proxy_pool_enabled)
        pool_row.addWidget(self.settings_proxy_pool_interval)
        pool_row.addStretch(1)
        card_layout.addLayout(pool_row)
        save = QPushButton("Save proxy settings")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_proxy_settings)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        card_layout.addLayout(actions)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_fingerprint_guard_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("Fingerprint Guard", "Choose how strictly the app blocks risky profile launches.")
        card, card_layout = self._settings_card()
        form = QFormLayout()
        self.compatibility_guard_mode_input = ModernComboBox()
        self.compatibility_guard_mode_input.addItem("Block risky launches", "block")
        self.compatibility_guard_mode_input.addItem("Warn only", "warn")
        self.compatibility_guard_mode_input.addItem("Off", "off")
        self.compatibility_guard_mode_input.setCurrentIndex(max(0, self.compatibility_guard_mode_input.findData(self.config_store.compatibility_guard_mode())))
        self.auto_snapshot_on_first_run_input = QCheckBox("Create a fingerprint baseline snapshot on first run")
        self.auto_snapshot_on_first_run_input.setChecked(self.config_store.auto_snapshot_on_first_run())
        form.addRow("Guard mode", self.compatibility_guard_mode_input)
        form.addRow("Baseline", self.auto_snapshot_on_first_run_input)
        card_layout.addLayout(form)
        hint = QLabel("Recommended: keep Guard mode on Block and baseline snapshots enabled for consistency checks.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)
        save = QPushButton("Save fingerprint guard")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_fingerprint_guard_settings)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save)
        card_layout.addLayout(row)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_data_backup_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("Data & Backup", "Extra protection for profile data, update installs and bulk actions.")
        card, card_layout = self._settings_card()
        self.settings_auto_backup_input = QCheckBox("Automatic backup")
        self.settings_auto_backup_input.setChecked(self.config_store.automatic_backup_enabled())
        self.settings_backup_interval = ModernComboBox()
        for label, value in (("Daily", 1), ("Every 3 days", 3), ("Weekly", 7)):
            self.settings_backup_interval.addItem(label, value)
        self.settings_backup_interval.setCurrentIndex(max(0, self.settings_backup_interval.findData(self.config_store.backup_interval_days())))
        self.backup_before_update_input = QCheckBox("Create backup before app updates")
        self.backup_before_update_input.setChecked(self.config_store.backup_before_update())
        self.backup_before_bulk_delete_input = QCheckBox("Create backup before bulk move to Trash")
        self.backup_before_bulk_delete_input.setChecked(self.config_store.backup_before_bulk_delete())
        backup_row = QHBoxLayout()
        backup_row.addWidget(self.settings_auto_backup_input)
        backup_row.addWidget(self.settings_backup_interval)
        backup_row.addStretch(1)
        card_layout.addLayout(backup_row)
        card_layout.addWidget(self.backup_before_update_input)
        card_layout.addWidget(self.backup_before_bulk_delete_input)
        buttons = QHBoxLayout()
        open_backup = QPushButton("Open Backup & Restore")
        open_backup.clicked.connect(partial(self.pages.setCurrentIndex, PAGE_BACKUP))
        save = QPushButton("Save data settings")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_data_backup_settings)
        buttons.addWidget(open_backup)
        buttons.addStretch(1)
        buttons.addWidget(save)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_update_settings_section(self) -> QWidget:
        page, layout = self._build_settings_section_page("Updates", "Check GitHub releases and install verified update packages.")
        update_card, update_layout = self._settings_card()
        mode_text = {
            "installed": "Installed edition - updates use the Windows installer",
            "portable": "Portable edition - updates replace only application files",
            "development": "Development mode - update checks are available for testing",
        }[self._installation_mode]
        self.app_update_mode_label = QLabel(mode_text)
        self.app_update_mode_label.setObjectName("pageSubtitle")
        self.app_update_mode_label.setWordWrap(True)
        update_layout.addWidget(self.app_update_mode_label)
        self.app_update_status = QLabel(tr(f"Current version: {APP_VERSION}"))
        self.app_update_status.setWordWrap(True)
        update_layout.addWidget(self.app_update_status)
        self.app_update_asset_label = QLabel("Asset: not checked yet")
        self.app_update_asset_label.setObjectName("hintLabel")
        self.app_update_asset_label.setWordWrap(True)
        update_layout.addWidget(self.app_update_asset_label)
        self.app_update_notes = QLabel("Release notes will appear here after checking GitHub.")
        self.app_update_notes.setObjectName("pageSubtitle")
        self.app_update_notes.setWordWrap(True)
        self.app_update_notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        update_layout.addWidget(self.app_update_notes)
        self.app_update_progress = QProgressBar()
        self.app_update_progress.setRange(0, 100)
        self.app_update_progress.setTextVisible(True)
        self.app_update_progress.hide()
        update_layout.addWidget(self.app_update_progress)
        update_buttons = QHBoxLayout()
        self.check_app_update_button = QPushButton("Check for updates")
        self.check_app_update_button.clicked.connect(self.check_app_update)
        self.install_app_update_button = QPushButton("Update now")
        self.install_app_update_button.setObjectName("primaryButton")
        self.install_app_update_button.clicked.connect(self.download_or_install_app_update)
        self.install_app_update_button.hide()
        self.open_release_button = QPushButton("Open release page")
        self.open_release_button.clicked.connect(self.open_latest_release_page)
        self.open_release_button.hide()
        update_buttons.addWidget(self.check_app_update_button)
        update_buttons.addWidget(self.install_app_update_button)
        update_buttons.addWidget(self.open_release_button)
        update_buttons.addStretch(1)
        update_layout.addLayout(update_buttons)
        layout.addWidget(update_card)
        layout.addStretch(1)
        return page

    def save_profile_defaults_settings(self) -> None:
        defaults = {
            "browser_engine": str(self.default_engine_input.currentData() or "cloak"),
            "platform": str(self.default_platform_input.currentData() or "windows"),
            "timezone": combo_value(self.default_timezone_input, DEFAULT_TIMEZONE),
            "locale": combo_value(self.default_locale_input, DEFAULT_LOCALE),
            "screen_width": int(self.default_width_input.value()),
            "screen_height": int(self.default_height_input.value()),
            "auto_geoip": self.default_auto_geoip_input.isChecked(),
            "group_name": self.default_group_input.text().strip(),
            "tags": self.default_tags_input.text().strip(),
        }
        self.config_store.set_profile_defaults(defaults)
        self.show_status("Profile defaults saved")

    def save_proxy_settings(self) -> None:
        self.config_store.set_proxy_check_before_run(self.proxy_check_before_run_input.isChecked())
        self.config_store.set_warn_profiles_without_proxy(self.warn_no_proxy_input.isChecked())
        self.config_store.set_proxy_pool_enabled(self.settings_proxy_pool_enabled.isChecked())
        self.config_store.set_proxy_pool_interval_minutes(int(self.settings_proxy_pool_interval.currentData() or 30))
        if hasattr(self, "proxy_pool_enabled"):
            blocker = QSignalBlocker(self.proxy_pool_enabled)
            self.proxy_pool_enabled.setChecked(self.config_store.proxy_pool_enabled())
            del blocker
        if hasattr(self, "proxy_pool_interval"):
            blocker = QSignalBlocker(self.proxy_pool_interval)
            self.proxy_pool_interval.setCurrentIndex(max(0, self.proxy_pool_interval.findData(self.config_store.proxy_pool_interval_minutes())))
            del blocker
        self.show_status("Proxy settings saved")

    def save_fingerprint_guard_settings(self) -> None:
        self.config_store.set_compatibility_guard_mode(str(self.compatibility_guard_mode_input.currentData() or "block"))
        self.config_store.set_auto_snapshot_on_first_run(self.auto_snapshot_on_first_run_input.isChecked())
        self.show_status("Fingerprint Guard settings saved")

    def save_data_backup_settings(self) -> None:
        self.config_store.set_automatic_backup_enabled(self.settings_auto_backup_input.isChecked())
        self.config_store.set_backup_interval_days(int(self.settings_backup_interval.currentData() or 1))
        self.config_store.set_backup_before_update(self.backup_before_update_input.isChecked())
        self.config_store.set_backup_before_bulk_delete(self.backup_before_bulk_delete_input.isChecked())
        if hasattr(self, "auto_backup_checkbox"):
            blocker = QSignalBlocker(self.auto_backup_checkbox)
            self.auto_backup_checkbox.setChecked(self.config_store.automatic_backup_enabled())
            del blocker
        if hasattr(self, "auto_backup_interval"):
            blocker = QSignalBlocker(self.auto_backup_interval)
            self.auto_backup_interval.setCurrentIndex(max(0, self.auto_backup_interval.findData(self.config_store.backup_interval_days())))
            del blocker
        self.show_status("Data and backup settings saved")

    def check_app_update(self) -> None:
        if self._update_check_thread is not None:
            self.show_status("An update check is already running")
            return
        self.check_app_update_button.setEnabled(False)
        self.install_app_update_button.hide()
        self.app_update_status.setText(tr("Checking GitHub for a newer version…"))
        self.task_center.add_task("Check for app updates", "GitHub", "app-update-check")
        thread = UpdateCheckThread(self)
        thread.completed.connect(self._app_update_checked)
        thread.failed.connect(self._app_update_failed)
        thread.finished.connect(self._update_check_finished)
        thread.finished.connect(thread.deleteLater)
        self._update_check_thread = thread
        thread.start()

    def _app_update_checked(self, info: AppUpdateInfo) -> None:
        self._available_app_update = info
        self._downloaded_app_update = None
        self.task_center.finish_task("app-update-check", f"Latest: {info.version}")
        url, sha256 = update_asset(info, self._installation_mode)
        asset_name = Path(urlparse(url).path).name or "update package"
        self.app_update_asset_label.setText(
            f"Edition: {self._installation_mode.title()} · Asset: {asset_name}\n"
            f"SHA-256: {sha256[:12]}...{sha256[-10:]} · verified after download"
        )
        self.app_update_notes.setText(info.notes or "No release notes were provided.")
        self.open_release_button.show()
        if not is_newer_version(info.version, APP_VERSION):
            self.app_update_status.setText(tr(
                f"You are up to date · version {APP_VERSION} is the latest version"
            ))
            self.install_app_update_button.hide()
            return
        notes = f"\n{info.notes}" if info.notes else ""
        self.app_update_status.setText(tr(
            f"Version {info.version} is available.{notes}"
        ))
        self.install_app_update_button.setText(tr("Update now"))
        self.install_app_update_button.show()

    def open_latest_release_page(self) -> None:
        info = self._available_app_update
        version = info.version if info else APP_VERSION
        QDesktopServices.openUrl(QUrl(f"https://github.com/Anhquocqh25/Cloakbrowser-Login-Pro/releases/tag/v{version}"))

    def _app_update_failed(self, message: str) -> None:
        self.app_update_status.setText(tr(f"Update check failed · {message}"))
        self.task_center.fail_task("app-update-check", message)
        self.show_error(message)

    def _update_check_finished(self) -> None:
        self._update_check_thread = None
        self.check_app_update_button.setEnabled(True)

    def download_or_install_app_update(self) -> None:
        info = self._available_app_update
        if info is None:
            self.check_app_update()
            return
        if self._downloaded_app_update and self._downloaded_app_update.is_file():
            self._install_downloaded_app_update()
            return
        if self.controller.has_background_work():
            self.show_error("Stop all running profiles and background checks before updating the app.")
            return
        if QMessageBox.question(
            self,
            tr("Install update"),
            tr(f"Download version {info.version} from GitHub now?\n\nThe file will be verified by SHA-256 before install."),
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if self.config_store.backup_before_update():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                backup_path = create_full_backup()
                self.show_status(f"Backup created before update: {backup_path}")
            except Exception as error:
                self.show_error(f"Could not create update backup: {error}")
                return
            finally:
                QApplication.restoreOverrideCursor()
        url, sha256 = update_asset(info, self._installation_mode)
        self.install_app_update_button.setEnabled(False)
        self.check_app_update_button.setEnabled(False)
        self.app_update_progress.setValue(0)
        self.app_update_progress.show()
        self.app_update_status.setText(tr(f"Downloading version {info.version}…"))
        self._install_after_download = True
        self.task_center.add_task("Download app update", f"Version {info.version}", "app-update-download")
        thread = UpdateDownloadThread(url, sha256, self)
        thread.progress.connect(self.app_update_progress.setValue)
        thread.progress.connect(lambda value: self.task_center.update_task("app-update-download", progress=value))
        thread.completed.connect(self._app_update_downloaded)
        thread.failed.connect(self._app_update_download_failed)
        thread.finished.connect(self._update_download_finished)
        thread.finished.connect(thread.deleteLater)
        self._update_download_thread = thread
        thread.start()

    def _app_update_downloaded(self, path: str) -> None:
        self._downloaded_app_update = Path(path)
        self.task_center.finish_task("app-update-download", "Downloaded and SHA-256 verified")
        self.app_update_status.setText(tr(
            "Update downloaded and verified. Installing…"
        ))
        self.install_app_update_button.setText(tr("Install update"))

    def _app_update_download_failed(self, message: str) -> None:
        self._install_after_download = False
        self.app_update_status.setText(tr(f"Update download failed · {message}"))
        self.task_center.fail_task("app-update-download", message)
        self.show_error(message)

    def _update_download_finished(self) -> None:
        self._update_download_thread = None
        self.check_app_update_button.setEnabled(True)
        self.install_app_update_button.setEnabled(True)
        self.app_update_progress.hide()
        if self._install_after_download and self._downloaded_app_update:
            self._install_after_download = False
            QTimer.singleShot(150, self._install_downloaded_app_update)

    def _install_downloaded_app_update(self) -> None:
        if self._downloaded_app_update is None or not self._downloaded_app_update.is_file():
            self.show_error("The downloaded update file is no longer available.")
            return
        if self.controller.has_background_work():
            self.show_error("Stop all running profiles and background checks before installing the update.")
            return
        try:
            launch_downloaded_update(
                self._downloaded_app_update,
                self._installation_mode,
                Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None,
            )
        except Exception as error:
            self.show_error(str(error))
            return
        self._allow_close = True
        QApplication.quit()

    def _apply_interface_language(self) -> None:
        selected = str(self.language_input.currentData() or "en")
        if selected == self.config_store.language():
            self.show_status("Language is already active")
            return
        if self.controller.has_background_work():
            self.show_error("Stop all running profiles before changing the interface language.")
            return
        self.config_store.set_language(selected)
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, []
        else:
            program = sys.executable
            arguments = [str(Path(__file__).resolve().parent.parent / "main.py"), *sys.argv[1:]]
        QProcess.startDetached(program, arguments)
        self._allow_close = True
        QApplication.quit()

    def _build_startup_page(self) -> QWidget:
        page, layout = self._new_data_page(
            "Startup website",
            "Set the website opened by default for profiles without a custom override",
        )
        card = QFrame()
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 22)
        card_layout.setSpacing(12)

        title = QLabel("Default startup website")
        title.setObjectName("editorSectionTitle")
        description = QLabel(
            "This address applies to every profile whose Startup website override is empty. "
            "To use a different page for one profile, open Settings → Overview. "
            "Use commas to open multiple tabs."
        )
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        self.default_startup_input = QLineEdit(self.config_store.default_startup_url())
        self.default_startup_input.setPlaceholderText("duckduckgo.com, iphey.com · leave empty for a blank tab")
        self.default_startup_input.setMinimumHeight(40)

        buttons = QHBoxLayout()
        save = QPushButton("Save default")
        save.setObjectName("primaryButton")
        clear = QPushButton("Clear")
        save.clicked.connect(self._save_default_startup)
        clear.clicked.connect(self._clear_default_startup)
        buttons.addWidget(save)
        buttons.addWidget(clear)
        buttons.addStretch(1)

        self.default_startup_status = QLabel()
        self.default_startup_status.setObjectName("hintLabel")
        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addWidget(self.default_startup_input)
        card_layout.addLayout(buttons)
        card_layout.addWidget(self.default_startup_status)
        layout.addWidget(card)
        layout.addStretch(1)
        self._refresh_default_startup_status()
        return page

    def _refresh_default_startup_status(self) -> None:
        current = self.config_store.default_startup_url()
        self.default_startup_status.setText(
            f"Current default: {current}" if current else "Current default: Blank tab"
        )

    def _save_default_startup(self) -> None:
        try:
            url = normalize_startup_url(self.default_startup_input.text())
        except ValueError as error:
            self.show_error(str(error))
            return
        self.default_startup_input.setText(url)
        self.config_store.set_default_startup_url(url)
        self._refresh_default_startup_status()
        self.show_status("Default startup website saved")

    def _clear_default_startup(self) -> None:
        self.default_startup_input.clear()
        self.config_store.set_default_startup_url("")
        self._refresh_default_startup_status()
        self.show_status("Default startup website cleared")

    def _build_extensions_page(self) -> QWidget:
        page, layout = self._new_data_page("Extensions", "Extensions enabled for every profile", "+ Add extension", self.add_extension)
        self.extensions_table = self._data_table(["Name", "Source", "Path", "Status", ""])
        header = self.extensions_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch)
        for index, width in ((1, 110), (3, 110), (4, 58)):
            header.setSectionResizeMode(index, QHeaderView.Fixed); self.extensions_table.setColumnWidth(index, width)
        layout.addWidget(self.extensions_table, 1)
        return page

    def _build_bookmarks_page(self) -> QWidget:
        page, layout = self._new_data_page("Bookmarks", "Bookmarks synchronized to every profile", "+ Add bookmark", self.add_bookmark)
        self.bookmarks_table = self._data_table(["Title", "Folder", "URL", ""])
        header = self.bookmarks_table.horizontalHeader()
        for index in (0, 1, 2): header.setSectionResizeMode(index, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed); self.bookmarks_table.setColumnWidth(3, 58)
        layout.addWidget(self.bookmarks_table, 1)
        return page

    def _build_trash_page(self) -> QWidget:
        page, layout = self._new_data_page(
            "Trash",
            "Deleted profiles are kept before permanent deletion",
            "Empty trash",
            self.empty_trash,
        )
        notice = QLabel(
            "Profile data, cookies and login sessions remain available until the profile is permanently deleted."
        )
        notice.setObjectName("pageSubtitle")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        trash_bar = QFrame(); trash_bar.setObjectName("bulkActionBar")
        trash_actions = QHBoxLayout(trash_bar); trash_actions.setContentsMargins(12, 7, 12, 7)
        self.trash_search = QLineEdit(); self.trash_search.setPlaceholderText("Search Trash")
        self.trash_search.setClearButtonEnabled(True); self.trash_search.setMaximumWidth(250)
        self.trash_select_all = QCheckBox("Select all")
        self.trash_restore_selected = QPushButton("Restore selected")
        self.trash_delete_selected = QPushButton("Delete selected permanently")
        self.trash_restore_selected.setEnabled(False); self.trash_delete_selected.setEnabled(False)
        retention = ModernComboBox()
        for days in (7, 15, 30): retention.addItem(f"Keep {days} days", days)
        retention.setCurrentIndex(max(0, retention.findData(self.config_store.trash_retention_days())))
        retention.currentIndexChanged.connect(lambda: self._set_trash_retention(int(retention.currentData())))
        trash_actions.addWidget(self.trash_search); trash_actions.addWidget(self.trash_select_all)
        trash_actions.addWidget(self.trash_restore_selected); trash_actions.addWidget(self.trash_delete_selected)
        trash_actions.addStretch(1); trash_actions.addWidget(retention)
        layout.addWidget(trash_bar)
        self.trash_table = self._data_table([
            "", "Name", "Deleted at", "Time remaining", "Proxy", "Actions",
        ])
        header = self.trash_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed); self.trash_table.setColumnWidth(0, 48)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed); self.trash_table.setColumnWidth(2, 170)
        header.setSectionResizeMode(3, QHeaderView.Fixed); self.trash_table.setColumnWidth(3, 130)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed); self.trash_table.setColumnWidth(5, 225)
        layout.addWidget(self.trash_table, 1)
        self.trash_search.textChanged.connect(self._filter_trash)
        self.trash_select_all.toggled.connect(self._toggle_trash_all)
        self.trash_restore_selected.clicked.connect(self.restore_selected_trash)
        self.trash_delete_selected.clicked.connect(self.delete_selected_trash)
        return page

    def _build_backup_page(self) -> QWidget:
        page, layout = self._new_data_page(
            "Backup & Restore", "Protect profiles, cookies, extensions and application settings"
        )
        card = QFrame(); card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card); card_layout.setContentsMargins(20, 18, 20, 18); card_layout.setSpacing(12)
        card_layout.addWidget(QLabel("Full application backup"))
        description = QLabel("Create a portable ZIP backup or restore one. A safety backup is created before every restore.")
        description.setObjectName("pageSubtitle"); description.setWordWrap(True); card_layout.addWidget(description)
        buttons = QHBoxLayout()
        backup = QPushButton("Create backup now"); backup.setObjectName("primaryButton"); backup.clicked.connect(self.create_backup)
        restore = QPushButton("Restore backup"); restore.clicked.connect(self.restore_backup)
        import_profile = QPushButton("Import profile"); import_profile.clicked.connect(self.import_profile)
        buttons.addWidget(backup); buttons.addWidget(restore); buttons.addWidget(import_profile); buttons.addStretch(1)
        card_layout.addLayout(buttons)
        auto_row = QHBoxLayout()
        self.auto_backup_checkbox = QCheckBox("Automatic backup")
        self.auto_backup_checkbox.setChecked(self.config_store.automatic_backup_enabled())
        self.auto_backup_interval = ModernComboBox()
        for label, value in (("Every day", 1), ("Every 3 days", 3), ("Every 7 days", 7)):
            self.auto_backup_interval.addItem(label, value)
        self.auto_backup_interval.setCurrentIndex(max(0, self.auto_backup_interval.findData(self.config_store.backup_interval_days())))
        self.auto_backup_checkbox.toggled.connect(self._save_backup_preferences)
        self.auto_backup_interval.currentIndexChanged.connect(self._save_backup_preferences)
        auto_row.addWidget(self.auto_backup_checkbox); auto_row.addWidget(self.auto_backup_interval); auto_row.addStretch(1)
        card_layout.addLayout(auto_row)
        self.backup_status = QLabel(f"Backup folder: {APP_BASE_DIR / 'backups'}")
        self.backup_status.setObjectName("hintLabel"); self.backup_status.setWordWrap(True); card_layout.addWidget(self.backup_status)
        layout.addWidget(card)

        recovery = QFrame(); recovery.setObjectName("settingsCard")
        recovery_layout = QVBoxLayout(recovery); recovery_layout.setContentsMargins(20, 18, 20, 18); recovery_layout.setSpacing(12)
        recovery_layout.addWidget(QLabel("Recovery Center"))
        recovery_description = QLabel(
            "Scan for browser profile folders that are not listed in app.db, recover them safely, "
            "and review automatic database snapshots."
        )
        recovery_description.setObjectName("pageSubtitle"); recovery_description.setWordWrap(True)
        recovery_layout.addWidget(recovery_description)
        recovery_buttons = QHBoxLayout()
        scan_recovery = QPushButton("Scan local data"); scan_recovery.clicked.connect(self.refresh_recovery_center)
        recover_orphans = QPushButton("Recover orphan profiles"); recover_orphans.setObjectName("primaryButton"); recover_orphans.clicked.connect(self.recover_orphan_profiles)
        open_backups = QPushButton("Open backup folder"); open_backups.clicked.connect(lambda: QProcess.startDetached("explorer.exe", [str(APP_BASE_DIR / "backups")]))
        recovery_buttons.addWidget(scan_recovery); recovery_buttons.addWidget(recover_orphans); recovery_buttons.addWidget(open_backups); recovery_buttons.addStretch(1)
        recovery_layout.addLayout(recovery_buttons)
        self.recovery_status = QLabel("Recovery Center has not scanned yet.")
        self.recovery_status.setObjectName("hintLabel"); self.recovery_status.setWordWrap(True)
        recovery_layout.addWidget(self.recovery_status)
        self.recovery_snapshot_table = self._data_table(["Snapshot", "Reason", "Modified", "Size"])
        snapshot_header = self.recovery_snapshot_table.horizontalHeader()
        snapshot_header.setSectionResizeMode(0, QHeaderView.Stretch)
        snapshot_header.setSectionResizeMode(1, QHeaderView.Fixed); self.recovery_snapshot_table.setColumnWidth(1, 100)
        snapshot_header.setSectionResizeMode(2, QHeaderView.Fixed); self.recovery_snapshot_table.setColumnWidth(2, 165)
        snapshot_header.setSectionResizeMode(3, QHeaderView.Fixed); self.recovery_snapshot_table.setColumnWidth(3, 110)
        self.recovery_snapshot_table.setMaximumHeight(230)
        recovery_layout.addWidget(self.recovery_snapshot_table)
        layout.addWidget(recovery); layout.addStretch(1)
        return page

    def _build_health_page(self) -> QWidget:
        page, layout = self._new_data_page(
            "Profile Health", "Preflight checks for proxy, IP, timezone, WebRTC, DNS and fingerprint consistency",
            "Check all profiles", self.controller.check_all_profile_health,
        )
        note = QLabel("Checks do not modify a profile fingerprint. They report configuration risks before launch.")
        note.setObjectName("pageSubtitle"); layout.addWidget(note)
        health_cards = QGridLayout(); health_cards.setHorizontalSpacing(12); health_cards.setVerticalSpacing(12)
        self.health_healthy_value = self._dashboard_card(health_cards, 0, "Healthy", "0", "Profiles with passed checks")
        self.health_warning_value = self._dashboard_card(health_cards, 1, "Warnings", "0", "Profiles needing review")
        self.health_failed_value = self._dashboard_card(health_cards, 2, "Failed", "0", "Profiles blocked by checks")
        self.health_unknown_value = self._dashboard_card(health_cards, 3, "Not checked", "0", "Profiles without a recent check")
        layout.addLayout(health_cards)
        health_actions = QFrame(); health_actions.setObjectName("bulkActionBar")
        health_action_layout = QHBoxLayout(health_actions); health_action_layout.setContentsMargins(12, 7, 12, 7)
        health_action_layout.addWidget(QLabel("Health dashboard"))
        open_profiles = QPushButton("Open Profiles"); open_profiles.clicked.connect(partial(self.pages.setCurrentIndex, PAGE_PROFILES))
        warnings_view = QPushButton("Show warnings"); warnings_view.clicked.connect(self.show_health_warnings_view)
        health_action_layout.addStretch(1); health_action_layout.addWidget(warnings_view); health_action_layout.addWidget(open_profiles)
        layout.addWidget(health_actions)
        self.health_table = self._data_table(["Checked at", "Profile", "Result", "Summary", "Details"])
        header = self.health_table.horizontalHeader()
        for index, width in ((0, 165), (2, 105)):
            header.setSectionResizeMode(index, QHeaderView.Fixed); self.health_table.setColumnWidth(index, width)
        for index in (1, 3, 4): header.setSectionResizeMode(index, QHeaderView.Stretch)
        layout.addWidget(self.health_table, 1)
        return page

    def _build_activity_page(self) -> QWidget:
        page, layout = self._new_data_page("Activity Log", "Profile operations, maintenance events and errors")
        controls = QFrame(); controls.setObjectName("bulkActionBar")
        row = QHBoxLayout(controls); row.setContentsMargins(12, 7, 12, 7)
        self.activity_search = QLineEdit(); self.activity_search.setPlaceholderText("Search activity"); self.activity_search.setClearButtonEnabled(True)
        self.activity_severity = ModernComboBox()
        for label, value in (("All levels", ""), ("Information", "info"), ("Warnings", "warning"), ("Errors", "error")):
            self.activity_severity.addItem(label, value)
        export = QPushButton("Export report"); export.clicked.connect(self.export_activity_report)
        clear = QPushButton("Clear log"); clear.clicked.connect(self.clear_activity_log)
        row.addWidget(self.activity_search); row.addWidget(self.activity_severity); row.addStretch(1); row.addWidget(export); row.addWidget(clear)
        layout.addWidget(controls)
        self.activity_table = self._data_table(["Time", "Level", "Action", "Profile", "Details"])
        header = self.activity_table.horizontalHeader()
        for index, width in ((0, 165), (1, 100)):
            header.setSectionResizeMode(index, QHeaderView.Fixed); self.activity_table.setColumnWidth(index, width)
        for index in (2, 3, 4): header.setSectionResizeMode(index, QHeaderView.Stretch)
        layout.addWidget(self.activity_table, 1)
        self.activity_search.textChanged.connect(self._filter_activity)
        self.activity_severity.currentIndexChanged.connect(self._filter_activity)
        return page

    def _build_fingerprint_page(self) -> QWidget:
        page, layout = self._new_data_page(
            "Fingerprint Lab",
            "Version control, consistency snapshots, Seed Lock, duplicates and regression testing",
            "Run regression test",
            self.run_regression_all,
        )

        version_card = QFrame(); version_card.setObjectName("settingsCard")
        version_layout = QHBoxLayout(version_card); version_layout.setContentsMargins(16, 12, 16, 12); version_layout.setSpacing(10)
        version_text = QVBoxLayout()
        self.cloak_version_title = QLabel("CloakBrowser core")
        self.cloak_version_title.setObjectName("editorSectionTitle")
        self.cloak_version_detail = QLabel("Reading installed version...")
        self.cloak_version_detail.setObjectName("pageSubtitle")
        self.cloak_version_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        version_text.addWidget(self.cloak_version_title); version_text.addWidget(self.cloak_version_detail)
        self.cloak_version_combo = ModernComboBox(); self.cloak_version_combo.setMinimumWidth(245)
        select_version = QPushButton("Use selected version"); select_version.clicked.connect(self.select_cloak_version)
        update_version = QPushButton("Check & download update"); update_version.setObjectName("primaryButton"); update_version.clicked.connect(self.check_cloak_update)
        version_layout.addLayout(version_text, 1); version_layout.addWidget(self.cloak_version_combo); version_layout.addWidget(select_version); version_layout.addWidget(update_version)
        layout.addWidget(version_card)

        tools = QFrame(); tools.setObjectName("bulkActionBar")
        tools_layout = QHBoxLayout(tools); tools_layout.setContentsMargins(12, 7, 12, 7); tools_layout.setSpacing(8)
        self.fp_selection_label = QLabel("0 selected")
        snapshot_selected = QPushButton("Snapshot selected"); snapshot_selected.clicked.connect(self.snapshot_selected_profiles)
        lock_selected = QPushButton("Lock selected seeds"); lock_selected.clicked.connect(self.lock_selected_seeds)
        refresh = QPushButton("Refresh analysis"); refresh.clicked.connect(self.controller.load_fingerprint_lab)
        tools_layout.addWidget(self.fp_selection_label); tools_layout.addWidget(snapshot_selected); tools_layout.addWidget(lock_selected)
        tools_layout.addStretch(1); tools_layout.addWidget(refresh)
        layout.addWidget(tools)

        self.fingerprint_table = self._data_table(["", "Profile", "Consistency", "Seed Lock", "Baseline", "Duplicates", "Current changes", "Actions"])
        header = self.fingerprint_table.horizontalHeader()
        for index, width in ((0, 46), (2, 125), (3, 105), (4, 155), (5, 100), (7, 70)):
            header.setSectionResizeMode(index, QHeaderView.Fixed); self.fingerprint_table.setColumnWidth(index, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.fingerprint_table, 1)

        history_title = QLabel("Recent snapshots & regression results"); history_title.setObjectName("editorSectionTitle")
        layout.addWidget(history_title)
        self.snapshot_table = self._data_table(["Time", "Profile", "Type", "Core version", "Result", "Changes"])
        self.snapshot_table.setMaximumHeight(220)
        snapshot_header = self.snapshot_table.horizontalHeader()
        for index, width in ((0, 155), (2, 95), (3, 175), (4, 90)):
            snapshot_header.setSectionResizeMode(index, QHeaderView.Fixed); self.snapshot_table.setColumnWidth(index, width)
        snapshot_header.setSectionResizeMode(1, QHeaderView.Stretch); snapshot_header.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.snapshot_table)
        self.fingerprint_checked_ids: set[str] = set()
        return page

    def _connect_signals(self) -> None:
        self.search_input.textChanged.connect(self._filter_profiles)
        self.profile_table.run_requested.connect(self.open_profile_by_id)
        self.profile_table.stop_requested.connect(self.close_profile_by_id)
        self.profile_table.edit_requested.connect(self.edit_profile_by_id)
        self.profile_table.clone_requested.connect(self.clone_profile_by_id)
        self.profile_table.delete_requested.connect(self.delete_profile_by_id)
        self.profile_table.rename_requested.connect(self.rename_profile)
        self.profile_table.widths_changed.connect(self._schedule_column_width_save)
        self.profile_table.checked_profiles_changed.connect(self._profile_selection_changed)
        self.profile_table.metadata_updated.connect(self.update_profile_metadata)
        self.profile_table.health_requested.connect(self.controller.check_profile_health)
        self.profile_table.export_requested.connect(self.export_profile_by_id)
        self.profile_table.compatibility_requested.connect(self.show_compatibility_report)
        self.profile_table.snapshot_requested.connect(self.show_fingerprint_snapshot_report)
        self.profile_table.itemSelectionChanged.connect(self._profile_row_selection_changed)
        self.controller.profiles_changed.connect(self.populate_profiles)
        self.controller.proxies_changed.connect(self.populate_proxies)
        self.controller.extensions_changed.connect(self.populate_extensions)
        self.controller.bookmarks_changed.connect(self.populate_bookmarks)
        self.controller.trash_changed.connect(self.populate_trash)
        self.controller.activity_changed.connect(self.populate_activity)
        self.controller.health_changed.connect(self.populate_health)
        self.controller.backup_completed.connect(self._backup_completed)
        self.controller.restore_completed.connect(self._restore_completed)
        self.controller.fingerprint_changed.connect(self.populate_fingerprint_lab)
        self.controller.cloak_versions_changed.connect(self.populate_cloak_versions)
        self.controller.task_started.connect(self._task_started)
        self.controller.task_progress.connect(self._task_progress)
        self.controller.task_finished.connect(self._task_finished)
        self.controller.operation_failed.connect(self.show_error)
        self.controller.info_message.connect(self.show_status)
        self.profile_editor.save_requested.connect(self._save_profile_editor)
        self.profile_editor.cancel_requested.connect(self._close_profile_editor)
        self._install_shortcuts()

    def _load_data(self) -> None:
        self.controller.load_proxies()
        self.controller.load_extensions()
        self.controller.load_bookmarks()
        self.controller.load_trash()
        self.controller.load_activity()
        self.controller.load_health()
        self.controller.load_fingerprint_lab()
        self.controller.load_profiles()
        self.refresh_recovery_center()
        QTimer.singleShot(350, self._maybe_show_onboarding)

    def populate_profiles(self, profiles: list[Profile]) -> None:
        self.profiles = profiles
        current_group = self.group_filter.currentData()
        current_tag = self.tag_filter.currentData() if hasattr(self, "tag_filter") else ""
        groups = sorted({profile.group_name for profile in profiles if profile.group_name}, key=str.casefold)
        tags = sorted({
            tag.strip()
            for profile in profiles
            for tag in profile.tags.replace(";", ",").split(",")
            if tag.strip()
        }, key=str.casefold)
        blocker = QSignalBlocker(self.group_filter)
        self.group_filter.clear(); self.group_filter.addItem("All groups", "")
        for group in groups: self.group_filter.addItem(group, group)
        self.group_filter.setCurrentIndex(max(0, self.group_filter.findData(current_group)))
        del blocker
        if hasattr(self, "tag_filter"):
            blocker = QSignalBlocker(self.tag_filter)
            self.tag_filter.clear(); self.tag_filter.addItem("All tags", "")
            for tag in tags: self.tag_filter.addItem(tag, tag)
            self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(current_tag)))
            del blocker
        self._filter_profiles()
        self._refresh_dashboard()
        self._refresh_health_summary()
        translate_tree(self.profile_table)

    def _filter_profiles(self) -> None:
        query = self.search_input.text().strip().lower()
        group = str(self.group_filter.currentData() or "")
        status = str(self.status_filter.currentData() or "")
        platform = str(self.os_filter.currentData() or "")
        quick = str(self.quick_filter.currentData() or "") if hasattr(self, "quick_filter") else ""
        tag = str(self.tag_filter.currentData() or "") if hasattr(self, "tag_filter") else ""
        visible = [profile for profile in self.profiles if not query or query in " ".join([
            profile.name, profile.notes, profile.group_name, profile.tags, profile.platform, profile.proxy or "", profile.locale, profile.status,
        ]).lower()]
        if group:
            visible = [profile for profile in visible if profile.group_name == group]
        if tag:
            visible = [
                profile for profile in visible
                if tag.casefold() in {item.strip().casefold() for item in profile.tags.replace(";", ",").split(",") if item.strip()}
            ]
        if platform:
            visible = [profile for profile in visible if profile.platform == platform]
        if status == "attention":
            visible = [profile for profile in visible if profile.health_status in {"warning", "fail"}]
        elif status:
            visible = [profile for profile in visible if profile.status == status]
        proxy_by_url = {proxy.url: proxy for proxy in self.proxies}
        if quick == "recent":
            visible = [profile for profile in visible if profile.last_used_at]
        elif quick == "warning":
            visible = [profile for profile in visible if profile.health_status in {"warning", "fail"}]
        elif quick == "no_proxy":
            visible = [profile for profile in visible if not profile.proxy]
        elif quick == "proxy_failed":
            visible = [profile for profile in visible if profile.proxy and proxy_by_url.get(profile.proxy) and proxy_by_url[profile.proxy].status == "dead"]
        elif quick == "running":
            visible = [profile for profile in visible if profile.status in {"running", "starting", "checking", "stopping"}]
        if self.pinned_filter.isChecked():
            visible = [profile for profile in visible if profile.pinned]
        sort_key = self.config_store.profile_sort()
        if sort_key == "created_desc":
            visible.sort(key=lambda profile: profile.created_at or "", reverse=True)
        elif sort_key == "created_asc":
            visible.sort(key=lambda profile: profile.created_at or "")
        elif sort_key == "name_asc":
            visible.sort(key=lambda profile: profile.name.casefold())
        elif sort_key == "name_desc":
            visible.sort(key=lambda profile: profile.name.casefold(), reverse=True)
        elif sort_key == "status":
            status_order = {"running": 0, "starting": 1, "checking": 2, "stopping": 3, "stopped": 4}
            visible.sort(key=lambda profile: (status_order.get(profile.status, 9), profile.name.casefold()))
        elif sort_key == "proxy":
            visible.sort(key=lambda profile: (not bool(profile.proxy), (profile.proxy or "").casefold(), profile.name.casefold()))
        visible.sort(key=lambda profile: not profile.pinned)
        self._last_visible_profiles = list(visible)
        self.profile_count.setText(tr(f"{len(visible)} profiles"))
        self.profile_table.set_profiles(visible)
        self.empty_profiles_hint.setVisible(len(visible) == 0)
        self._update_filter_summary()
        self._refresh_profile_preview()

    def _sort_profiles_changed(self, *_args) -> None:
        self.config_store.set_profile_sort(str(self.sort_input.currentData() or "created_desc"))
        self._filter_profiles()

    def _profile_density_changed(self, *_args) -> None:
        density = str(self.density_input.currentData() or "comfortable")
        self.config_store.set_profile_density(density)
        self.profile_table.set_density(density)
        self._update_filter_summary()
        self.show_status(f"Table density set to {density}")

    @staticmethod
    def _combo_values(combo: QComboBox) -> list[str]:
        return [str(combo.itemData(index) or "") for index in range(combo.count()) if str(combo.itemData(index) or "")]

    @staticmethod
    def _combo_current_label(combo: QComboBox) -> str:
        return str(combo.currentText() or "").strip()

    def _current_filter_state(self) -> dict[str, object]:
        return {
            "group": str(self.group_filter.currentData() or ""),
            "status": str(self.status_filter.currentData() or ""),
            "platform": str(self.os_filter.currentData() or ""),
            "quick": str(self.quick_filter.currentData() or ""),
            "tag": str(self.tag_filter.currentData() or ""),
            "density": str(self.density_input.currentData() or "comfortable"),
            "pinned": self.pinned_filter.isChecked(),
        }

    def open_advanced_filters(self) -> None:
        groups = self._combo_values(self.group_filter)
        tags = self._combo_values(self.tag_filter)
        dialog = AdvancedFiltersDialog(groups, tags, self._current_filter_state(), self)
        if dialog.exec() != AdvancedFiltersDialog.Accepted:
            return
        filters = dialog.filters()
        blockers = [
            QSignalBlocker(self.group_filter),
            QSignalBlocker(self.os_filter),
            QSignalBlocker(self.tag_filter),
            QSignalBlocker(self.density_input),
            QSignalBlocker(self.pinned_filter),
        ]
        self.group_filter.setCurrentIndex(max(0, self.group_filter.findData(str(filters["group"]))))
        self.os_filter.setCurrentIndex(max(0, self.os_filter.findData(str(filters["platform"]))))
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(str(filters["tag"]))))
        self.density_input.setCurrentIndex(max(0, self.density_input.findData(str(filters["density"]))))
        self.pinned_filter.setChecked(bool(filters["pinned"]))
        del blockers
        density = str(self.density_input.currentData() or "comfortable")
        self.config_store.set_profile_density(density)
        self.profile_table.set_density(density)
        self._filter_profiles()

    def reset_profile_filters(self) -> None:
        blockers = [
            QSignalBlocker(self.search_input),
            QSignalBlocker(self.saved_view_input),
            QSignalBlocker(self.group_filter),
            QSignalBlocker(self.status_filter),
            QSignalBlocker(self.os_filter),
            QSignalBlocker(self.quick_filter),
            QSignalBlocker(self.tag_filter),
            QSignalBlocker(self.density_input),
            QSignalBlocker(self.pinned_filter),
        ]
        self.search_input.clear()
        self.saved_view_input.setCurrentIndex(0)
        self.group_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(0)
        self.os_filter.setCurrentIndex(0)
        self.quick_filter.setCurrentIndex(0)
        self.tag_filter.setCurrentIndex(0)
        self.density_input.setCurrentIndex(max(0, self.density_input.findData("comfortable")))
        self.pinned_filter.setChecked(False)
        del blockers
        self.config_store.set_profile_density("comfortable")
        self.profile_table.set_density("comfortable")
        self._filter_profiles()
        self.show_status("Profile filters cleared")

    def _update_filter_summary(self) -> None:
        if not hasattr(self, "filter_summary"):
            return
        active: list[str] = []
        if self.search_input.text().strip():
            active.append("Search")
        if self.group_filter.currentData():
            active.append(f"Group: {self._combo_current_label(self.group_filter)}")
        if self.os_filter.currentData():
            active.append(f"OS: {self._combo_current_label(self.os_filter)}")
        if self.tag_filter.currentData():
            active.append(f"Tag: {self._combo_current_label(self.tag_filter)}")
        if self.status_filter.currentData():
            active.append(f"State: {self._combo_current_label(self.status_filter)}")
        if self.quick_filter.currentData():
            active.append(f"Quick: {self._combo_current_label(self.quick_filter)}")
        if self.pinned_filter.isChecked():
            active.append("Pinned")
        density = str(self.density_input.currentData() or "comfortable")
        if density != "comfortable":
            active.append(f"Density: {self._combo_current_label(self.density_input)}")
        if active:
            self.filter_summary.setText("Active: " + "  |  ".join(active[:4]) + (f"  +{len(active) - 4}" if len(active) > 4 else ""))
        else:
            self.filter_summary.setText("No extra filters")

    def _schedule_column_width_save(self, widths: dict[str, int]) -> None:
        self._pending_widths = widths
        self.width_save_timer.start()

    def _flush_column_widths(self) -> None:
        if self._pending_widths:
            self.config_store.set_column_widths(self._pending_widths)

    def open_column_settings(self) -> None:
        visible = self.config_store.visible_columns(self.profile_table.default_visible_keys)
        dialog = ColumnSettingsDialog(PROFILE_COLUMNS, visible, self)

        def apply_visibility(keys: list[str]) -> None:
            self.profile_table.set_visible_columns(keys)
            self.config_store.set_visible_columns(keys)

        dialog.visibility_changed.connect(apply_visibility)
        dialog.exec()
        apply_visibility(dialog.visible_keys())

    def _profile_defaults_payload(self) -> dict[str, object]:
        return self.config_store.profile_defaults()

    def create_profile(self) -> None:
        dialog = ProfileDialog(
            self,
            proxies=self.proxies,
            default_startup_url=self.config_store.default_startup_url(),
            defaults=self._profile_defaults_payload(),
        )
        if dialog.exec() == ProfileDialog.Accepted:
            try: self.controller.create_profile(**dialog.get_payload())
            except Exception as error: self.show_error(str(error))

    def create_profiles_batch(self) -> None:
        dialog = BatchCreateDialog(
            self,
            self.proxies,
            default_startup_url=self.config_store.default_startup_url(),
            defaults=self._profile_defaults_payload(),
        )
        if dialog.exec() != BatchCreateDialog.Accepted:
            return
        payloads = dialog.payloads()
        existing_names = {profile.name.casefold() for profile in self.profiles}
        duplicates = [str(payload["name"]) for payload in payloads if str(payload["name"]).casefold() in existing_names]
        if duplicates:
            preview = ", ".join(duplicates[:4])
            if len(duplicates) > 4:
                preview += f" and {len(duplicates) - 4} more"
            answer = QMessageBox.question(
                self,
                "Duplicate profile names",
                f"These names already exist: {preview}.\n\nCreate them anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            self.controller.create_profiles_batch(payloads)
        except Exception as error:
            self.show_error(str(error))

    def _maybe_show_onboarding(self) -> None:
        if self.config_store.onboarding_completed():
            return
        dialog = OnboardingDialog(
            self.config_store.language(), self.config_store.default_startup_url(),
            bool(self.profiles), self,
        )
        if dialog.exec() == OnboardingDialog.Accepted:
            payload = dialog.payload()
            try:
                startup = normalize_startup_url(str(payload["startup_url"] or ""))
            except ValueError as error:
                self.show_error(str(error)); startup = ""
            self.config_store.set_default_startup_url(startup)
            language = str(payload["language"])
            self.config_store.set_language(language); set_language(language); translate_tree(self)
            if payload.get("create_sample") and not self.profiles:
                self.controller.create_profile(
                    "Welcome Profile", None, "Asia/Bangkok", "en-US", 1200, 800,
                    platform="windows", notes="Sample · ready to customize",
                )
        self.config_store.set_onboarding_completed(True)
        self._refresh_default_startup_status()

    def show_onboarding_again(self) -> None:
        self.config_store.set_onboarding_completed(False)
        self._maybe_show_onboarding()

    def save_selected_as_preset(self) -> None:
        if len(self._selected_profile_ids) != 1:
            self.show_status("Select exactly one profile to save as a preset")
            return
        profile = self.controller.get_profile(self._selected_profile_ids[0])
        if not profile:
            return
        name, accepted = QInputDialog.getText(self, tr("Save profile preset"), tr("Preset name"), text=profile.name)
        if not accepted or not name.strip():
            return
        preset = {
            "name": name.strip(), "proxy": profile.proxy or "", "timezone": profile.timezone,
            "locale": profile.locale, "screen_width": profile.screen_width,
            "screen_height": profile.screen_height, "auto_geoip": profile.auto_geoip,
            "platform": profile.platform, "browser_engine": profile.browser_engine,
            "notes": profile.notes, "user_agent": profile.user_agent,
            "startup_url": profile.startup_url, "group_name": profile.group_name,
            "tags": profile.tags, "extension_ids": profile.extension_ids,
            "bookmark_ids": profile.bookmark_ids,
        }
        presets = [item for item in self.config_store.profile_presets() if str(item.get("name", "")).casefold() != name.strip().casefold()]
        presets.append(preset); self.config_store.set_profile_presets(presets)
        self.show_status(f"Saved preset {name.strip()}")

    def create_from_preset(self) -> None:
        presets = self.config_store.profile_presets()
        if not presets:
            self.show_status("No presets yet · select one profile and choose Save selected as preset")
            return
        dialog = PresetChoiceDialog(presets, self)
        result = dialog.exec()
        self.config_store.set_profile_presets(dialog.presets)
        if result != PresetChoiceDialog.Accepted or not dialog.selected:
            return
        preset = dict(dialog.selected)
        base_name = str(preset.pop("name", "Preset Profile"))
        existing = {profile.name.casefold() for profile in self.profiles}
        name = base_name; counter = 2
        while name.casefold() in existing:
            name = f"{base_name} {counter:02d}"; counter += 1
        try:
            self.controller.create_profile(name=name, **preset)
        except Exception as error:
            self.show_error(str(error))

    def bulk_edit_selected_profiles(self) -> None:
        if not self._selected_profile_ids:
            return
        dialog = BulkEditDialog(len(self._selected_profile_ids), self.proxies, self.extensions, self.bookmarks, self)
        if dialog.exec() != BulkEditDialog.Accepted:
            return
        try:
            snapshots = self.controller.bulk_update_profiles(self._selected_profile_ids, dialog.payload())
            self._push_undo("Undo bulk profile edit", partial(self.controller.restore_profile_snapshots, snapshots))
            self.profile_table.clear_checked()
        except Exception as error:
            self.show_error(str(error))

    def _push_undo(self, label: str, callback) -> None:
        self._undo_stack.append((label, callback)); self._undo_stack = self._undo_stack[-20:]
        self.undo_button.setText(tr(label)); self.undo_button.show()
        QTimer.singleShot(15000, self._hide_undo_if_same)

    def _hide_undo_if_same(self) -> None:
        if self._undo_stack:
            self.undo_button.hide()

    def _undo_last_action(self) -> None:
        if not self._undo_stack:
            self.undo_button.hide(); return
        _label, callback = self._undo_stack.pop()
        try:
            callback()
            self.show_status("Last action was undone")
        except Exception as error:
            self.show_error(str(error))
        self.undo_button.setVisible(bool(self._undo_stack))

    def _load_saved_views(self) -> None:
        blocker = QSignalBlocker(self.saved_view_input)
        self.saved_view_input.clear(); self.saved_view_input.addItem("All profiles", "")
        for index, view in enumerate(self.config_store.saved_views()):
            self.saved_view_input.addItem(str(view.get("name") or f"View {index + 1}"), index)
        del blocker

    def save_current_view(self) -> None:
        name, accepted = QInputDialog.getText(self, tr("Save current view"), tr("View name"))
        if not accepted or not name.strip():
            return
        view = {
            "name": name.strip(), "query": self.search_input.text(),
            "group": str(self.group_filter.currentData() or ""),
            "status": str(self.status_filter.currentData() or ""),
            "platform": str(self.os_filter.currentData() or ""),
            "quick": str(self.quick_filter.currentData() or ""),
            "tag": str(self.tag_filter.currentData() or ""),
            "density": str(self.density_input.currentData() or "comfortable"),
            "pinned": self.pinned_filter.isChecked(),
            "sort": str(self.sort_input.currentData() or "created_desc"),
            "columns": [spec.key for index, spec in enumerate(PROFILE_COLUMNS) if not self.profile_table.isColumnHidden(index)],
        }
        views = [item for item in self.config_store.saved_views() if str(item.get("name", "")).casefold() != name.strip().casefold()]
        views.append(view); self.config_store.set_saved_views(views); self._load_saved_views()
        self.saved_view_input.setCurrentIndex(self.saved_view_input.count() - 1)

    def delete_current_view(self) -> None:
        index = self.saved_view_input.currentData()
        if index in (None, ""):
            return
        views = self.config_store.saved_views()
        if 0 <= int(index) < len(views):
            views.pop(int(index)); self.config_store.set_saved_views(views); self._load_saved_views(); self._filter_profiles()

    def _apply_saved_view(self, *_args) -> None:
        if not hasattr(self, "saved_view_input"):
            return
        index = self.saved_view_input.currentData()
        if index in (None, ""):
            return
        views = self.config_store.saved_views()
        if not 0 <= int(index) < len(views):
            return
        view = views[int(index)]
        blockers = [QSignalBlocker(widget) for widget in (self.search_input, self.group_filter, self.status_filter, self.os_filter, self.quick_filter, self.tag_filter, self.density_input, self.pinned_filter, self.sort_input)]
        self.search_input.setText(str(view.get("query") or ""))
        self.group_filter.setCurrentIndex(max(0, self.group_filter.findData(str(view.get("group") or ""))))
        self.status_filter.setCurrentIndex(max(0, self.status_filter.findData(str(view.get("status") or ""))))
        self.os_filter.setCurrentIndex(max(0, self.os_filter.findData(str(view.get("platform") or ""))))
        self.quick_filter.setCurrentIndex(max(0, self.quick_filter.findData(str(view.get("quick") or ""))))
        self.tag_filter.setCurrentIndex(max(0, self.tag_filter.findData(str(view.get("tag") or ""))))
        self.density_input.setCurrentIndex(max(0, self.density_input.findData(str(view.get("density") or "comfortable"))))
        self.pinned_filter.setChecked(bool(view.get("pinned")))
        self.sort_input.setCurrentIndex(max(0, self.sort_input.findData(str(view.get("sort") or "created_desc"))))
        del blockers
        columns = view.get("columns")
        if isinstance(columns, list): self.profile_table.set_visible_columns([str(item) for item in columns])
        self.config_store.set_profile_density(str(view.get("density") or "comfortable"))
        self.profile_table.set_density(self.config_store.profile_density())
        self.config_store.set_profile_sort(str(view.get("sort") or "created_desc")); self._filter_profiles()

    def open_command_palette(self) -> None:
        commands = [
            ("create", "Create profile", "Ctrl+N"), ("batch", "Create batch", "Ctrl+Shift+N"),
            ("find", "Search profiles", "Ctrl+F"), ("run", "Run selected profiles", "Ctrl+Enter"),
            ("stop", "Stop selected profiles", ""), ("health", "Check selected profiles", ""),
            ("edit", "Bulk edit selected", "Ctrl+Shift+B"), ("tag", "Add tag to selected", ""),
            ("proxy", "Check all proxies", ""),
            ("dashboard", "Open Dashboard", "Ctrl+1"), ("profiles", "Open Profiles", "Ctrl+2"),
            ("health_page", "Open Profile Health", ""), ("fingerprint", "Open Fingerprint Lab", ""),
            ("updates", "Check app updates", ""), ("undo", "Undo", "Ctrl+Z"),
        ]
        dialog = CommandPaletteDialog(commands, self)
        if dialog.exec() != CommandPaletteDialog.Accepted:
            return
        actions = {
            "create": self.create_profile, "batch": self.create_profiles_batch,
            "find": self.focus_profile_search, "run": self.open_selected_profiles,
            "stop": self.stop_selected_profiles, "health": self.check_selected_profiles,
            "edit": self.bulk_edit_selected_profiles, "tag": self.bulk_add_tag,
            "proxy": self.controller.check_all_proxies,
            "dashboard": partial(self.pages.setCurrentIndex, PAGE_DASHBOARD),
            "profiles": partial(self.pages.setCurrentIndex, PAGE_PROFILES),
            "health_page": partial(self.pages.setCurrentIndex, PAGE_HEALTH),
            "fingerprint": partial(self.pages.setCurrentIndex, PAGE_FINGERPRINT),
            "updates": partial(self.pages.setCurrentIndex, PAGE_SETTINGS),
            "undo": self._undo_last_action,
        }
        action = actions.get(dialog.command_key)
        if action: action()

    def _selected_or_current_profile_ids(self) -> list[str]:
        if self._selected_profile_ids:
            return list(dict.fromkeys(self._selected_profile_ids))
        profile = self._current_table_profile()
        return [profile.id] if profile else []

    def _current_table_profile(self) -> Profile | None:
        row = self.profile_table.currentRow()
        if row < 0 or row >= len(self.profile_table.profiles):
            return None
        return self.profile_table.profiles[row]

    def _profile_row_selection_changed(self) -> None:
        self._refresh_profile_preview(self._current_table_profile())

    def _refresh_profile_preview(self, profile: Profile | None = None) -> None:
        if not hasattr(self, "preview_fields"):
            return
        profile = profile or self._current_table_profile()
        if not profile:
            self.preview_status.setText("Select a profile to see details")
            for value in self.preview_fields.values():
                value.setText("—")
            self.preview_run_button.setEnabled(False)
            self.preview_edit_button.setEnabled(False)
            self.preview_health_button.setEnabled(False)
            return
        proxy = next((item for item in self.proxies if item.url == profile.proxy), None)
        platform = {"windows": "Windows 11", "macos": "macOS", "linux": "Linux"}.get(profile.platform, profile.platform)
        health = {"pass": "Healthy", "warning": "Needs attention", "fail": "Failed", "unknown": "Not checked"}.get(profile.health_status, profile.health_status)
        proxy_text = "No proxy"
        if profile.proxy:
            proxy_text = proxy.name if proxy else "Custom proxy"
            if proxy and proxy.location:
                proxy_text += f" · {proxy.location}"
            if proxy:
                proxy_text += f" · {proxy.status}"
        startup = profile.startup_url or self.config_store.default_startup_url() or "Blank tab"
        self.preview_status.setText(f"{profile.status.title()} · {health}")
        values = {
            "name": profile.name,
            "group": profile.group_name or "No group",
            "tags": profile.tags or "No tags",
            "state": profile.status,
            "health": f"{health} · {profile.health_checked_at.replace('T', ' ')[:16] if profile.health_checked_at else 'not checked'}",
            "proxy": proxy_text,
            "os": f"{platform} · {profile.screen_size_label}",
            "locale": profile.locale,
            "timezone": profile.timezone,
            "seed": str(profile.fingerprint_seed or "Auto") + (" · locked" if profile.seed_locked else ""),
            "startup": startup,
        }
        for key, value in values.items():
            self.preview_fields[key].setText(value)
        running = profile.status in {"running", "starting", "checking", "stopping"}
        self.preview_run_button.setText("Stop" if running else "Run")
        self.preview_run_button.setEnabled(profile.status not in {"starting", "checking", "stopping"})
        self.preview_edit_button.setEnabled(profile.status == "stopped")
        self.preview_health_button.setEnabled(profile.id not in getattr(self.controller, "health_threads", {}))

    def run_preview_profile(self) -> None:
        profile = self._current_table_profile()
        if not profile:
            return
        if profile.status == "running":
            self.close_profile_by_id(profile.id)
        else:
            self.open_profile_by_id(profile.id)

    def edit_preview_profile(self) -> None:
        profile = self._current_table_profile()
        if profile:
            self.edit_profile_by_id(profile.id)

    def check_preview_profile(self) -> None:
        profile = self._current_table_profile()
        if profile:
            self.controller.check_profile_health(profile.id)

    def stop_selected_profiles(self) -> None:
        ids = self._selected_or_current_profile_ids()
        stopped = 0
        errors: list[str] = []
        for profile_id in ids:
            profile = self.controller.get_profile(profile_id)
            if not profile or profile.status == "stopped":
                continue
            try:
                self.controller.close_profile(profile_id, silent=True)
                stopped += 1
            except Exception as error:
                errors.append(f"{profile.name}: {error}")
        self.show_status(f"Stopping {stopped} profile(s)" if stopped else "No active selected profiles")
        if errors:
            self.show_error("\n".join(errors[:6]))

    def check_selected_profiles(self) -> None:
        ids = self._selected_or_current_profile_ids()
        if not ids:
            self.show_status("Select profiles to check")
            return
        for profile_id in ids:
            self.controller.check_profile_health(profile_id)
        self.show_status(f"Checking health for {len(ids)} profile(s)")

    def export_selected_profile(self) -> None:
        ids = self._selected_or_current_profile_ids()
        if len(ids) != 1:
            self.show_status("Select exactly one profile to export")
            return
        self.export_profile_by_id(ids[0])

    def bulk_set_group(self) -> None:
        ids = self._selected_or_current_profile_ids()
        if not ids:
            self.show_status("Select profiles first")
            return
        group, accepted = QInputDialog.getText(self, tr("Set group"), tr("Group name"))
        if not accepted:
            return
        for profile_id in ids:
            try:
                self.controller.update_profile_metadata(profile_id, "group_name", group.strip())
            except Exception as error:
                self.show_error(str(error)); return
        self.show_status(f"Updated group for {len(ids)} profile(s)")

    def bulk_add_tag(self) -> None:
        ids = self._selected_or_current_profile_ids()
        if not ids:
            self.show_status("Select profiles first")
            return
        tag, accepted = QInputDialog.getText(self, tr("Add tag"), tr("Tag"))
        tag = tag.strip()
        if not accepted or not tag:
            return
        for profile_id in ids:
            profile = self.controller.get_profile(profile_id)
            if not profile:
                continue
            tags = [item.strip() for item in profile.tags.replace(";", ",").split(",") if item.strip()]
            if tag.casefold() not in {item.casefold() for item in tags}:
                tags.append(tag)
            self.controller.update_profile_metadata(profile_id, "tags", ", ".join(tags))
        self.show_status(f"Added tag to {len(ids)} profile(s)")

    def bulk_clear_tags(self) -> None:
        ids = self._selected_or_current_profile_ids()
        if not ids:
            self.show_status("Select profiles first")
            return
        if QMessageBox.question(self, tr("Clear tags"), tr(f"Clear tags from {len(ids)} profile(s)?"), QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for profile_id in ids:
            self.controller.update_profile_metadata(profile_id, "tags", "")
        self.show_status(f"Cleared tags from {len(ids)} profile(s)")

    def show_group_tag_summary(self) -> None:
        groups: dict[str, int] = {}
        tags: dict[str, int] = {}
        for profile in self.profiles:
            groups[profile.group_name or "No group"] = groups.get(profile.group_name or "No group", 0) + 1
            for tag in [item.strip() for item in profile.tags.replace(";", ",").split(",") if item.strip()]:
                tags[tag] = tags.get(tag, 0) + 1
        group_text = "\n".join(f"• {name}: {count}" for name, count in sorted(groups.items(), key=lambda item: item[0].casefold())) or "No groups"
        tag_text = "\n".join(f"• {name}: {count}" for name, count in sorted(tags.items(), key=lambda item: item[0].casefold())) or "No tags"
        QMessageBox.information(self, tr("Groups & Tags"), f"Groups\n{group_text}\n\nTags\n{tag_text}")

    def _toggle_all_profiles(self, state: int) -> None:
        # A user click may briefly enter the partial state on a tri-state box;
        # treat every non-empty state as "select all" and then normalize it.
        self.profile_table.set_all_checked(state != Qt.CheckState.Unchecked.value)

    def _profile_selection_changed(self, profile_ids: list[str]) -> None:
        self._selected_profile_ids = list(profile_ids)
        count = len(profile_ids)
        self.selection_count.setText(tr(f"{count} selected"))
        self.bulk_open_button.setEnabled(count > 0)
        self.bulk_stop_button.setEnabled(count > 0)
        self.bulk_health_button.setEnabled(count > 0)
        self.bulk_export_button.setEnabled(count == 1)
        self.bulk_delete_button.setEnabled(count > 0)
        self.bulk_edit_button.setEnabled(count > 0)

        blocker = QSignalBlocker(self.select_all_checkbox)
        if count == 0:
            self.select_all_checkbox.setCheckState(Qt.Unchecked)
        elif count == self.profile_table.rowCount() and self.profile_table.rowCount() > 0:
            self.select_all_checkbox.setCheckState(Qt.Checked)
        else:
            self.select_all_checkbox.setCheckState(Qt.PartiallyChecked)
        del blocker

    def open_selected_profiles(self) -> None:
        selected = [self.controller.get_profile(profile_id) for profile_id in self._selected_profile_ids]
        profiles = [profile for profile in selected if profile and profile.status == "stopped"]
        skipped = len(selected) - len(profiles)
        if not profiles:
            self.show_status("No ready profiles selected")
            return
        direct_count = sum(1 for profile in profiles if not profile.proxy)
        if direct_count and self.config_store.warn_profiles_without_proxy():
            answer = QMessageBox.warning(
                self,
                "Profiles without proxy",
                f"{direct_count} selected profile(s) will use the machine IP. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        errors: list[str] = []
        for profile in profiles:
            try:
                self.controller.open_profile(profile.id)
            except Exception as error:
                errors.append(f"{profile.name}: {error}")
        self.profile_table.clear_checked()
        opened = len(profiles) - len(errors)
        message = f"Opening {opened} profile(s)"
        if skipped:
            message += f" · skipped {skipped} active profile(s)"
        self.show_status(message)
        if errors:
            self.show_error("Some profiles could not be opened:\n" + "\n".join(errors[:6]))

    def delete_selected_profiles(self) -> None:
        profiles = [self.controller.get_profile(profile_id) for profile_id in self._selected_profile_ids]
        profiles = [profile for profile in profiles if profile]
        if not profiles:
            return
        names = ", ".join(profile.name for profile in profiles[:4])
        if len(profiles) > 4:
            names += f" and {len(profiles) - 4} more"
        answer = QMessageBox.question(
            self,
            "Move selected profiles to Trash",
            f"Move {len(profiles)} profile(s) to Trash?\n\n{names}\n\nThey will be permanently deleted after {self.config_store.trash_retention_days()} days.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if self.config_store.backup_before_bulk_delete():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                backup_path = create_full_backup()
                self.show_status(f"Safety backup created before bulk Trash: {backup_path}")
            except Exception as error:
                self.show_error(f"Could not create safety backup: {error}")
                return
            finally:
                QApplication.restoreOverrideCursor()

        errors: list[str] = []
        for profile in profiles:
            try:
                self.controller.delete_profile(profile.id)
            except Exception as error:
                errors.append(f"{profile.name}: {error}")
        self.profile_table.clear_checked()
        successful_ids = [profile.id for profile in profiles if not any(message.startswith(f"{profile.name}:") for message in errors)]
        if successful_ids:
            self._offer_trash_undo(successful_ids)
        self.show_status(f"Moved or queued {len(profiles) - len(errors)} profile(s) for Trash")
        if errors:
            self.show_error("Some profiles could not be moved to Trash:\n" + "\n".join(errors[:6]))

    def edit_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile: return self.show_error("Profile not found")
        if profile.status != "stopped":
            return self.show_error("Stop this profile before editing its settings.")
        self.profile_editor.load_profile(
            profile,
            self.proxies,
            self.extensions,
            self.bookmarks,
            self.config_store.default_startup_url(),
        )
        self.pages.setCurrentWidget(self.profile_editor)

    def _save_profile_editor(self, profile_id: str, payload: dict) -> None:
        try:
            self.controller.update_profile(profile_id, **payload)
        except Exception as error:
            self.show_error(str(error))
            return
        self._close_profile_editor()

    def _close_profile_editor(self) -> None:
        self.pages.setCurrentIndex(0)
        buttons = self.nav_group.buttons()
        if buttons:
            buttons[0].setChecked(True)

    def rename_profile(self, profile_id: str, name: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile or profile.name == name: return
        try:
            self.controller.update_profile_metadata(profile.id, "name", name)
        except Exception as error:
            self.show_error(str(error)); self.controller.load_profiles()

    def update_profile_metadata(self, profile_id: str, field: str, value: object) -> None:
        try:
            if field == "name":
                self.rename_profile(profile_id, str(value))
            else:
                self.controller.update_profile_metadata(profile_id, field, value)
        except Exception as error:
            self.show_error(str(error)); self.controller.load_profiles()

    def close_all_profiles(self) -> None:
        count = self.controller.close_all_profiles()
        self.show_status(f"Closing {count} active profile(s)" if count else "No active profiles")

    def open_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile: return self.show_error("Profile not found")
        if not profile.proxy and self.config_store.warn_profiles_without_proxy():
            answer = QMessageBox.warning(self, "No proxy", "This profile will use the machine IP. Continue?", QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes: return
        try: self.controller.open_profile(profile_id)
        except Exception as error: self.show_error(str(error))

    def close_profile_by_id(self, profile_id: str) -> None:
        try: self.controller.close_profile(profile_id)
        except Exception as error: self.show_error(str(error))

    def show_compatibility_report(self, profile_id: str) -> None:
        try:
            report = self.controller.profile_compatibility(profile_id)
        except Exception as error:
            self.show_error(str(error)); return
        profile = self.controller.get_profile(profile_id)
        lines = [f"{profile.name if profile else 'Profile'} · {report.score}/100 · {report.status.title()}"]
        if report.issues:
            for item in report.issues:
                fix = f"\nFix: {item.fix}" if item.fix else ""
                lines.append(f"\n{'BLOCK' if item.severity == 'blocker' else 'WARN'} · {item.title}\n{item.detail}{fix}")
        else:
            lines.append("\nAll compatibility checks passed.")
        QMessageBox.information(self, tr("Fingerprint Compatibility Guard"), "\n".join(lines))

    def show_fingerprint_snapshot_report(self, profile_id: str) -> None:
        try:
            report = self.controller.profile_snapshot_report(profile_id)
        except Exception as error:
            self.show_error(str(error)); return
        profile = report["profile"]
        snapshot = dict(report["snapshot"])
        consistency = report["consistency"]
        compatibility = report["compatibility"]
        proxy = report.get("proxy")
        lines = [
            f"{profile.name} · fingerprint snapshot",
            f"Hash: {str(report['fingerprint_hash'])[:16]}...",
            "",
            f"Compatibility: {compatibility.status} · {compatibility.score}/100",
            f"Consistency: {consistency.status} · {consistency.score}/100",
            "",
            f"Engine: {snapshot.get('engine')}",
            f"Cloak core: {snapshot.get('cloak_version') or 'auto'}",
            f"Seed: {snapshot.get('fingerprint_seed')} · locked: {snapshot.get('seed_locked')}",
            f"Platform: {snapshot.get('platform')}",
            f"Screen: {snapshot.get('screen')}",
            f"Locale: {snapshot.get('locale')}",
            f"Timezone: {snapshot.get('timezone')}",
            f"User-Agent: {snapshot.get('user_agent')}",
            f"Proxy mode: {snapshot.get('proxy_mode')}",
            f"WebRTC policy: {snapshot.get('webrtc_policy')}",
            f"DNS route: {snapshot.get('dns_route')}",
        ]
        if proxy:
            lines.extend([
                "",
                f"Proxy: {proxy.name} · {proxy.status}",
                f"Exit IP: {proxy.exit_ip or 'not checked'}",
                f"Location: {proxy.location or 'unknown'}",
                f"Timezone: {proxy.timezone or 'unknown'}",
                f"Quality: {proxy.quality_score}/100",
            ])
        if compatibility.issues:
            lines.append("")
            lines.append("Issues:")
            for item in compatibility.issues[:8]:
                lines.append(f"- {item.severity.upper()} · {item.title}: {item.detail}")
        QMessageBox.information(self, tr("Fingerprint Snapshot"), "\n".join(lines))

    def clone_profile_by_id(self, profile_id: str) -> None:
        try: self.controller.clone_profile(profile_id)
        except Exception as error: self.show_error(str(error))

    def delete_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if profile and QMessageBox.question(
            self,
            "Move profile to Trash",
            f"Move {profile.name} to Trash? It will be permanently deleted after {self.config_store.trash_retention_days()} days.",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            try:
                self.controller.delete_profile(profile_id)
                self._offer_trash_undo([profile_id])
            except Exception as error: self.show_error(str(error))

    def populate_trash(self, profiles: list[Profile]) -> None:
        self.deleted_profiles = profiles
        self._trash_checked_ids.intersection_update(profile.id for profile in profiles)
        self._filter_trash()

    def _filter_trash(self) -> None:
        query = self.trash_search.text().strip().casefold()
        profiles = [profile for profile in self.deleted_profiles if not query or query in f"{profile.name} {profile.proxy or ''} {profile.notes}".casefold()]
        self._render_trash(profiles)

    def _render_trash(self, profiles: list[Profile]) -> None:
        self.trash_table.setRowCount(len(profiles))
        now = datetime.utcnow()
        retention_days = self.config_store.trash_retention_days()
        for row, profile in enumerate(profiles):
            try:
                deleted_at = datetime.fromisoformat(profile.deleted_at)
                expires_at = deleted_at + timedelta(days=retention_days)
                days_remaining = max(0, math.ceil((expires_at - now).total_seconds() / 86400))
                deleted_text = deleted_at.strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                days_remaining = 0
                deleted_text = profile.deleted_at or "—"
            checkbox = QCheckBox(); checkbox.setChecked(profile.id in self._trash_checked_ids)
            checkbox.toggled.connect(partial(self._trash_checked, profile.id))
            holder = QWidget(); holder_layout = QHBoxLayout(holder); holder_layout.setContentsMargins(8, 0, 0, 0); holder_layout.addWidget(checkbox); holder_layout.addStretch(1)
            self.trash_table.setCellWidget(row, 0, holder)
            values = (
                profile.name,
                deleted_text,
                f"{days_remaining} day(s)",
                profile.proxy or "No proxy",
            )
            for column, value in enumerate(values, start=1):
                self._set_item(self.trash_table, row, column, value, column == 1)
            holder = QWidget()
            actions = QHBoxLayout(holder)
            actions.setContentsMargins(4, 4, 4, 4)
            actions.setSpacing(6)
            restore = QPushButton("Restore")
            restore.setFixedHeight(30)
            restore.clicked.connect(partial(self.restore_profile, profile))
            permanent = QPushButton("Delete permanently")
            permanent.setFixedHeight(30)
            permanent.clicked.connect(partial(self.delete_profile_permanently, profile))
            actions.addWidget(restore)
            actions.addWidget(permanent)
            self.trash_table.setCellWidget(row, 5, holder)
        self._trash_selection_changed()
        translate_tree(self.trash_table)

    def _trash_checked(self, profile_id: str, checked: bool) -> None:
        if checked: self._trash_checked_ids.add(profile_id)
        else: self._trash_checked_ids.discard(profile_id)
        self._trash_selection_changed()

    def _trash_selection_changed(self) -> None:
        count = len(self._trash_checked_ids)
        self.trash_restore_selected.setEnabled(count > 0)
        self.trash_delete_selected.setEnabled(count > 0)
        blocker = QSignalBlocker(self.trash_select_all)
        self.trash_select_all.setChecked(bool(self.deleted_profiles) and count == len(self.deleted_profiles))
        del blocker

    def _toggle_trash_all(self, checked: bool) -> None:
        visible_ids = {profile.id for profile in self.deleted_profiles if not self.trash_search.text().strip() or self.trash_search.text().strip().casefold() in f"{profile.name} {profile.proxy or ''} {profile.notes}".casefold()}
        if checked: self._trash_checked_ids.update(visible_ids)
        else: self._trash_checked_ids.difference_update(visible_ids)
        self._filter_trash()

    def restore_selected_trash(self) -> None:
        for profile_id in list(self._trash_checked_ids):
            try: self.controller.restore_profile(profile_id)
            except Exception as error: self.show_error(str(error))
        self._trash_checked_ids.clear()

    def delete_selected_trash(self) -> None:
        if QMessageBox.warning(self, "Delete permanently", "Permanently delete selected profiles? This cannot be undone.", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for profile_id in list(self._trash_checked_ids):
            try: self.controller.delete_profile_permanently(profile_id)
            except Exception as error: self.show_error(str(error))
        self._trash_checked_ids.clear()

    def _set_trash_retention(self, days: int) -> None:
        self.config_store.set_trash_retention_days(days)
        self.controller.purge_expired_profiles()
        self._filter_trash()
        self.show_status(f"Trash retention set to {days} days")

    def _offer_trash_undo(self, profile_ids: list[str]) -> None:
        self._last_trashed_ids = list(profile_ids)
        self._push_undo("Undo delete", self._undo_last_trash)

    def _undo_last_trash(self) -> None:
        for profile_id in self._last_trashed_ids:
            try: self.controller.restore_profile(profile_id)
            except Exception: pass
        self._last_trashed_ids = []

    def restore_profile(self, profile: Profile) -> None:
        try:
            self.controller.restore_profile(profile.id)
        except Exception as error:
            self.show_error(str(error))

    def delete_profile_permanently(self, profile: Profile) -> None:
        answer = QMessageBox.warning(
            self,
            "Delete permanently",
            f"Permanently delete {profile.name}? All cookies, login sessions and profile data will be removed. This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.controller.delete_profile_permanently(profile.id)
        except Exception as error:
            self.show_error(str(error))

    def empty_trash(self) -> None:
        if self.trash_table.rowCount() == 0:
            self.show_status("Trash is empty")
            return
        answer = QMessageBox.warning(
            self,
            "Empty trash",
            "Permanently delete every profile in Trash? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            try:
                self.controller.empty_trash()
            except Exception as error:
                self.show_error(str(error))

    def create_backup(self) -> None:
        default_name = str((APP_BASE_DIR / "backups" / f"cloak-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"))
        path, _ = QFileDialog.getSaveFileName(self, tr("Create backup now"), default_name, "ZIP archives (*.zip)")
        if not path: return
        try: self.controller.create_backup(path)
        except Exception as error: self.show_error(str(error))

    def restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Restore backup"), str(APP_BASE_DIR / "backups"), "ZIP archives (*.zip)")
        if not path: return
        if QMessageBox.warning(
            self, tr("Restore backup"),
            tr("Current profiles and settings will be replaced. A safety backup will be created first. Continue?"),
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try: self.controller.restore_backup(path)
        except Exception as error: self.show_error(str(error))

    def _backup_completed(self, path: str) -> None:
        self.backup_status.setText(f"Last backup: {path}")
        self.refresh_recovery_center()

    def _restore_completed(self) -> None:
        self.refresh_recovery_center()
        QMessageBox.information(self, tr("Restore complete"), tr("Backup restored successfully. Restart the app to reload all interface settings."))

    def _save_backup_preferences(self, *_args) -> None:
        self.config_store.set_automatic_backup_enabled(self.auto_backup_checkbox.isChecked())
        self.config_store.set_backup_interval_days(int(self.auto_backup_interval.currentData() or 1))

    def refresh_recovery_center(self) -> None:
        if not hasattr(self, "recovery_snapshot_table"):
            return
        try:
            status = self.controller.recovery_center_status()
        except Exception as error:
            self.recovery_status.setText(f"Recovery scan failed: {error}")
            return
        orphan_ids = [str(item) for item in status.get("orphan_ids", [])]
        snapshots = list(status.get("database_snapshots", []))
        if orphan_ids:
            self.recovery_status.setText(
                f"Found {len(orphan_ids)} orphan profile folder(s): {', '.join(orphan_ids[:4])}"
                f"{'...' if len(orphan_ids) > 4 else ''}"
            )
        else:
            self.recovery_status.setText("No orphan profile folders found. Database snapshots are listed below.")
        self.recovery_snapshot_table.setRowCount(len(snapshots))
        for row, snapshot in enumerate(snapshots):
            values = (
                str(snapshot.get("name", "")),
                str(snapshot.get("reason", "")) or "manual",
                str(snapshot.get("modified_at", "")).replace("T", " ")[:19],
                self._format_bytes(int(snapshot.get("size", 0) or 0)),
            )
            for column, value in enumerate(values):
                self._set_item(self.recovery_snapshot_table, row, column, value, column == 0)

    def recover_orphan_profiles(self) -> None:
        try:
            status = self.controller.recovery_center_status()
        except Exception as error:
            self.show_error(str(error)); return
        count = int(status.get("orphan_count", 0) or 0)
        if count <= 0:
            self.show_status("No orphan profile folders found")
            self.refresh_recovery_center()
            return
        if QMessageBox.question(
            self,
            tr("Recover orphan profiles"),
            tr(f"Recover {count} profile folder(s) that are not listed in app.db? A safety backup will be created first."),
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self.controller.recover_orphaned_profile_data()
            restored = int(result.get("recovered_profiles", 0) or 0) + int(result.get("recovered_deleted_profiles", 0) or 0)
            self.show_status(f"Recovered {restored} profile(s)")
            self.refresh_recovery_center()
        except Exception as error:
            self.show_error(str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def export_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile: return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export profile"), f"{profile.name}-profile.zip", "ZIP archives (*.zip)")
        if not path: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self.controller.export_profile_archive(profile_id, path)
            self.show_status(f"Profile exported: {result}")
        except Exception as error: self.show_error(str(error))
        finally: QApplication.restoreOverrideCursor()

    def import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Import profile"), "", "ZIP archives (*.zip)")
        if not path: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            profile = self.controller.import_profile_archive(path)
            self.show_status(f"Imported profile {profile.name}")
        except Exception as error: self.show_error(str(error))
        finally: QApplication.restoreOverrideCursor()

    def populate_health(self, records: list[dict]) -> None:
        self.health_table.setRowCount(len(records))
        colors = {"pass": "#0d8f78", "warning": "#d97706", "fail": "#c2414b"}
        for row, record in enumerate(records):
            details = record.get("details") or {}
            details_text = " · ".join(
                f"{name}: {value.get('message', '')}" for name, value in details.items()
            )
            values = (
                str(record.get("timestamp", "")).replace("T", " ")[:19],
                str(record.get("profile_name", "")), str(record.get("status", "")).title(),
                str(record.get("summary", "")), details_text,
            )
            for column, value in enumerate(values): self._set_item(self.health_table, row, column, value, column == 1)
            self.health_table.item(row, 2).setForeground(QColor(colors.get(str(record.get("status")), "#6b7280")))
        translate_tree(self.health_table)
        self._refresh_health_summary(records)

    def _refresh_health_summary(self, records: list[dict] | None = None) -> None:
        if not hasattr(self, "health_healthy_value"):
            return
        statuses = [profile.health_status or "unknown" for profile in self.profiles]
        self.health_healthy_value.setText(str(sum(status == "pass" for status in statuses)))
        self.health_warning_value.setText(str(sum(status == "warning" for status in statuses)))
        self.health_failed_value.setText(str(sum(status == "fail" for status in statuses)))
        self.health_unknown_value.setText(str(sum(status not in {"pass", "warning", "fail"} for status in statuses)))

    def show_health_warnings_view(self) -> None:
        self.pages.setCurrentIndex(PAGE_PROFILES)
        self.status_filter.setCurrentIndex(max(0, self.status_filter.findData("attention")))
        self.quick_filter.setCurrentIndex(max(0, self.quick_filter.findData("warning")))
        self._filter_profiles()

    def populate_activity(self, records: list[dict]) -> None:
        self.activity_records = records
        self._filter_activity()

    def _filter_activity(self) -> None:
        if not hasattr(self, "activity_records"): return
        query = self.activity_search.text().strip().casefold()
        severity = str(self.activity_severity.currentData() or "")
        records = [record for record in self.activity_records if (not severity or record.get("severity") == severity) and (not query or query in " ".join(str(record.get(key, "")) for key in ("action", "profile_name", "details")).casefold())]
        self.activity_table.setRowCount(len(records))
        colors = {"info": "#0d8f78", "warning": "#d97706", "error": "#c2414b"}
        for row, record in enumerate(records):
            values = (
                str(record.get("timestamp", "")).replace("T", " ")[:19],
                str(record.get("severity", "info")).title(), str(record.get("action", "")),
                str(record.get("profile_name", "")) or "—", str(record.get("details", "")) or "—",
            )
            for column, value in enumerate(values): self._set_item(self.activity_table, row, column, value, column == 3)
            self.activity_table.item(row, 1).setForeground(QColor(colors.get(str(record.get("severity")), "#6b7280")))
        translate_tree(self.activity_table)

    def export_activity_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Export report"), f"cloak-activity-{datetime.now():%Y%m%d}.csv", "CSV files (*.csv)")
        if not path: return
        try: self.show_status(f"Report exported: {self.controller.export_activity_report(path)}")
        except Exception as error: self.show_error(str(error))

    def clear_activity_log(self) -> None:
        if QMessageBox.question(self, tr("Clear log"), tr("Clear all activity history?"), QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.controller.maintenance_repository.clear_activity()
        self.controller.load_activity()

    def populate_cloak_versions(self, info: dict) -> None:
        version = str(info.get("version") or "unknown")
        wrapper = str(info.get("wrapper_version") or "unknown")
        state = "Installed" if info.get("installed") else "Not installed"
        self.cloak_version_detail.setText(
            f"Wrapper {wrapper} · Core {version} · {state} · {info.get('tier', '')}\n{info.get('binary_path', '')}"
        )
        current = str(info.get("pinned_version") or "")
        blocker = QSignalBlocker(self.cloak_version_combo)
        self.cloak_version_combo.clear()
        self.cloak_version_combo.addItem("Automatic / bundled", "")
        for cached in info.get("cached_versions", []):
            self.cloak_version_combo.addItem(str(cached), str(cached))
        self.cloak_version_combo.setCurrentIndex(max(0, self.cloak_version_combo.findData(current)))
        del blocker

    def select_cloak_version(self) -> None:
        try:
            self.controller.set_cloak_version(str(self.cloak_version_combo.currentData() or ""))
            self.show_status("CloakBrowser version selection saved")
        except Exception as error:
            self.show_error(str(error))

    def check_cloak_update(self) -> None:
        try: self.controller.check_cloak_update()
        except Exception as error: self.show_error(str(error))

    def populate_fingerprint_lab(self, payload: dict) -> None:
        self.fingerprint_payload = payload
        profiles = list(payload.get("profiles") or [])
        valid_ids = {str(item.get("profile_id")) for item in profiles}
        self.fingerprint_checked_ids.intersection_update(valid_ids)
        self.fingerprint_table.setRowCount(len(profiles))
        colors = {"pass": "#0d8f78", "warning": "#d97706", "fail": "#c2414b"}
        for row, record in enumerate(profiles):
            profile_id = str(record.get("profile_id"))
            checkbox = QCheckBox(); checkbox.setChecked(profile_id in self.fingerprint_checked_ids)
            checkbox.toggled.connect(partial(self._fingerprint_checked, profile_id))
            check_holder = QWidget(); check_layout = QHBoxLayout(check_holder); check_layout.setContentsMargins(8, 0, 0, 0); check_layout.addWidget(checkbox); check_layout.addStretch(1)
            self.fingerprint_table.setCellWidget(row, 0, check_holder)
            status = str(record.get("consistency_status") or "unknown")
            differences = dict(record.get("differences") or {})
            duplicate_count = int(record.get("duplicate_count") or 0)
            values = (
                str(record.get("name") or ""),
                f"{record.get('score', 0)}/100 · {status.title()}",
                "Locked" if record.get("seed_locked") else "Unlocked",
                str(record.get("baseline_at") or "No baseline").replace("T", " ")[:19],
                str(duplicate_count) if duplicate_count else "None",
                ", ".join(differences) if differences else "No changes",
            )
            for column, value in enumerate(values, start=1):
                self._set_item(self.fingerprint_table, row, column, value, column == 1)
            self.fingerprint_table.item(row, 2).setForeground(QColor(colors.get(status, "#6b7280")))
            checks_text = "\n".join(f"{item.get('name')}: {item.get('status')} · {item.get('message')}" for item in record.get("checks", []))
            self.fingerprint_table.item(row, 2).setToolTip(checks_text)
            duplicate_text = "\n".join(f"{item.get('name')}: {item.get('reason')}" for item in record.get("duplicates", []))
            self.fingerprint_table.item(row, 5).setToolTip(duplicate_text or "No duplicate fingerprint configuration")
            self.fingerprint_table.setCellWidget(row, 7, self._menu_button([
                ("View analysis", partial(self.show_fingerprint_analysis, record)),
                ("Create snapshot", partial(self.create_snapshot_by_id, profile_id)),
                ("Run regression", partial(self.run_regression_profile, profile_id)),
                ("Unlock seed" if record.get("seed_locked") else "Lock seed", partial(self.toggle_seed_lock, profile_id, not bool(record.get("seed_locked")))),
            ]))

        snapshots = list(payload.get("snapshots") or [])
        self.snapshot_table.setRowCount(len(snapshots))
        for row, record in enumerate(snapshots):
            changes = dict(record.get("differences") or {})
            values = (
                str(record.get("created_at") or "").replace("T", " ")[:19],
                str(record.get("profile_name") or ""), str(record.get("kind") or "").title(),
                str(record.get("cloak_version") or "—"), str(record.get("status") or "").title(),
                ", ".join(changes) if changes else "No changes",
            )
            for column, value in enumerate(values): self._set_item(self.snapshot_table, row, column, value, column == 1)
            self.snapshot_table.item(row, 4).setForeground(QColor(colors.get(str(record.get("status")), "#6b7280")))
        self.fp_selection_label.setText(tr(f"{len(self.fingerprint_checked_ids)} selected"))
        translate_tree(self.fingerprint_table); translate_tree(self.snapshot_table)

    def _fingerprint_checked(self, profile_id: str, checked: bool) -> None:
        if checked: self.fingerprint_checked_ids.add(profile_id)
        else: self.fingerprint_checked_ids.discard(profile_id)
        self.fp_selection_label.setText(tr(f"{len(self.fingerprint_checked_ids)} selected"))

    def show_fingerprint_analysis(self, record: dict) -> None:
        checks = "\n".join(f"• {item.get('name')}: {item.get('status')} — {item.get('message')}" for item in record.get("checks", []))
        duplicates = "\n".join(f"• {item.get('name')}: {item.get('reason')}" for item in record.get("duplicates", [])) or "None"
        changes = ", ".join((record.get("differences") or {}).keys()) or "No changes"
        QMessageBox.information(self, tr("Fingerprint analysis"), f"{record.get('name')} · {record.get('score')}/100\n\n{checks}\n\nDuplicates:\n{duplicates}\n\nChanges: {changes}")

    def create_snapshot_by_id(self, profile_id: str) -> None:
        try:
            result = self.controller.create_fingerprint_snapshot(profile_id)
            self.show_status(f"Fingerprint snapshot created · {result['status']}")
        except Exception as error: self.show_error(str(error))

    def snapshot_selected_profiles(self) -> None:
        if not self.fingerprint_checked_ids:
            self.show_status("Select profiles in Fingerprint Lab first")
            return
        errors = []
        for profile_id in list(self.fingerprint_checked_ids):
            try: self.controller.create_fingerprint_snapshot(profile_id)
            except Exception as error: errors.append(str(error))
        if errors: self.show_error("\n".join(errors[:5]))

    def toggle_seed_lock(self, profile_id: str, locked: bool) -> None:
        if not locked and QMessageBox.warning(
            self, tr("Unlock fingerprint seed"),
            tr("Unlocking allows the profile identity seed to change. Continue?"),
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try: self.controller.set_seed_locked(profile_id, locked)
        except Exception as error: self.show_error(str(error))

    def lock_selected_seeds(self) -> None:
        if not self.fingerprint_checked_ids:
            self.show_status("Select profiles in Fingerprint Lab first")
            return
        for profile_id in list(self.fingerprint_checked_ids):
            try: self.controller.set_seed_locked(profile_id, True)
            except Exception as error: self.show_error(str(error))

    def run_regression_profile(self, profile_id: str) -> None:
        try:
            result = self.controller.run_regression_test([profile_id])
            if result: self.show_status(f"Regression result: {result[0]['status']}")
        except Exception as error: self.show_error(str(error))

    def run_regression_all(self) -> None:
        try:
            results = self.controller.run_regression_test()
            failed = sum(1 for item in results if item["status"] == "fail")
            self.show_status(f"Regression tested {len(results)} profile(s) · {failed} failed")
        except Exception as error: self.show_error(str(error))

    def create_sample_profiles(self) -> None:
        existing = {profile.name for profile in self.profiles}
        samples = [
            ("profile 1", "Windows 11 · General"),
            ("Click to change name", "Windows 11 · Rename me"),
            ("Facebook", "Windows 11 · Social"),
            ("Google", "Windows 11 · Workspace"),
            ("Coinlist", "Windows 11 · Finance"),
            ("Linkedin", "Windows 11 · Work"),
        ]
        for name, notes in samples:
            if name in existing: continue
            self.controller.create_profile(name, None, "Asia/Bangkok", "en-US", 1200, 800, platform="windows", notes=notes)

    # Auxiliary pages
    @staticmethod
    def _format_bytes(size: int) -> str:
        value = float(max(0, size))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:.1f} GB"

    def _set_item(self, table: QTableWidget, row: int, column: int, text: str, bold: bool = False) -> None:
        item = QTableWidgetItem(text or "—"); item.setToolTip(text or "—")
        if bold: item.setFont(QFont(self.font().family(), 10, QFont.DemiBold))
        table.setItem(row, column, item)

    def _menu_button(self, actions: list[tuple[str, object]]) -> QWidget:
        holder = QWidget(); layout = QHBoxLayout(holder); layout.setContentsMargins(4, 0, 8, 0)
        button = QToolButton(); button.setObjectName("rowMoreButton"); button.setText("..."); button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        for label, callback in actions:
            if label == "---": menu.addSeparator()
            else: menu.addAction(label, callback)
        button.setMenu(menu); layout.addWidget(button)
        return holder

    def populate_proxies(self, records: list[ProxyRecord]) -> None:
        self.proxies = records; self.profile_table.set_proxy_records(records)
        self.proxies_table.setRowCount(len(records))
        for row, record in enumerate(records):
            parsed = urlparse(record.url); address = f"{parsed.hostname or ''}:{parsed.port or ''}".rstrip(":")
            status_labels = {
                "checking": "Checking...", "live": "● Live",
                "dead": "● Dead", "unknown": "Not checked",
            }
            status_text = status_labels.get(record.status, record.status.title())
            result_text = (
                f"{record.exit_ip} · {record.latency_ms} ms"
                if record.status == "live" else (f"{record.latency_ms} ms" if record.latency_ms else "—")
            )
            checked_text = record.last_checked_at.replace("T", " ")[:16] if record.last_checked_at else "—"
            pool_text = "Enabled" if record.enabled else "Cooldown"
            values = (
                record.name, record.proxy_type, address, record.location, record.notes,
                status_text, f"{record.quality_score}/100", pool_text, result_text, checked_text,
            )
            for col, value in enumerate(values):
                self._set_item(self.proxies_table, row, col, value, col == 0)
            if record.country_code:
                self.proxies_table.item(row, 3).setIcon(country_flag_icon(record.country_code))
            status_item = self.proxies_table.item(row, 5)
            status_item.setForeground(QColor({"live": "#0d8f78", "dead": "#c2414b", "checking": "#d97706"}.get(record.status, "#6b7280")))
            status_item.setToolTip(record.check_error or status_text)
            self.proxies_table.setCellWidget(row, 10, self._menu_button([
                ("Check proxy", partial(self.controller.check_proxy, record.id)),
                ("Disable in pool" if record.enabled else "Enable in pool", partial(self.controller.set_proxy_enabled, record.id, not record.enabled)),
                ("Edit", partial(self.edit_proxy, record)), ("---", None),
                ("Delete", partial(self.delete_proxy, record)),
            ]))
        self._refresh_dashboard()
        translate_tree(self.proxies_table)

    def add_proxy(self) -> None: self.edit_proxy(None)

    def edit_proxy(self, record: ProxyRecord | None) -> None:
        dialog = ProxyDialog(self, record)
        if dialog.exec() == ProxyDialog.Accepted:
            try:
                saved = self.controller.save_proxy(**dialog.payload())
                self.controller.check_proxy(saved.id)
            except Exception as error: self.show_error(str(error))

    def delete_proxy(self, record: ProxyRecord) -> None:
        if QMessageBox.question(self, "Delete proxy", f"Delete {record.name}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try: self.controller.delete_proxy(record.id)
            except Exception as error: self.show_error(str(error))

    def populate_extensions(self, records: list[ExtensionRecord]) -> None:
        self.extensions = records; self.extensions_table.setRowCount(len(records) + 1)
        for col, value in enumerate(("Default Bookmarks", "Built-in", "Managed by app", "Enabled")):
            self._set_item(self.extensions_table, 0, col, value, col == 0)
        for row, record in enumerate(records, start=1):
            try:
                source = "URL" if Path(record.path).resolve().is_relative_to(EXTENSION_STORAGE_DIR.resolve()) else "Folder"
            except OSError:
                source = "Folder"
            for col, value in enumerate((record.name, source, record.path, "Enabled" if record.enabled else "Disabled")):
                self._set_item(self.extensions_table, row, col, value, col == 0)
            self.extensions_table.setCellWidget(row, 4, self._menu_button([
                ("Disable" if record.enabled else "Enable", partial(self.controller.toggle_extension, record.id)),
                ("---", None), ("Delete", partial(self.controller.delete_extension, record.id)),
            ]))
        translate_tree(self.extensions_table)

    def add_extension(self) -> None:
        dialog = AddExtensionDialog(self)
        if dialog.exec() != AddExtensionDialog.Accepted:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.statusBar().showMessage("Downloading and validating extension..." if dialog.mode == "url" else "Adding extension...")
        QApplication.processEvents()
        try:
            if dialog.mode == "url":
                record = self.controller.add_extension_from_url(dialog.value)
            else:
                record = self.controller.add_extension(dialog.value)
            self.show_status(f"Added extension {record.name}")
        except Exception as error:
            self.show_error(str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def populate_bookmarks(self, records: list[BookmarkRecord]) -> None:
        self.bookmarks = records; self.bookmarks_table.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, value in enumerate((record.title, record.folder, record.url)):
                self._set_item(self.bookmarks_table, row, col, value, col == 0)
            self.bookmarks_table.setCellWidget(row, 3, self._menu_button([
                ("Edit", partial(self.edit_bookmark, record)), ("---", None), ("Delete", partial(self.delete_bookmark, record)),
            ]))
        translate_tree(self.bookmarks_table)

    def add_bookmark(self) -> None: self.edit_bookmark(None)

    def edit_bookmark(self, record: BookmarkRecord | None) -> None:
        dialog = BookmarkDialog(self, record)
        if dialog.exec() == BookmarkDialog.Accepted:
            try: self.controller.save_bookmark(**dialog.payload())
            except Exception as error: self.show_error(str(error))

    def delete_bookmark(self, record: BookmarkRecord) -> None:
        if QMessageBox.question(self, "Delete bookmark", f"Delete {record.title}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.controller.delete_bookmark(record.id)

    def _refresh_dashboard(self) -> None:
        if not hasattr(self, "dashboard_profiles_value"):
            return
        running = sum(profile.status in {"running", "starting", "checking"} for profile in self.profiles)
        available = sum(proxy.enabled and proxy.status == "live" for proxy in self.proxies)
        attention = sum(profile.health_status in {"warning", "fail"} for profile in self.profiles)
        self.dashboard_profiles_value.setText(str(len(self.profiles)))
        self.dashboard_running_value.setText(str(running))
        self.dashboard_proxy_value.setText(f"{available}/{len(self.proxies)}")
        self.dashboard_health_value.setText(str(attention))
        recent = sorted(self.profiles, key=lambda profile: profile.last_used_at or profile.created_at or "", reverse=True)[:7]
        self.dashboard_recent.setRowCount(len(recent))
        proxy_by_url = {proxy.url: proxy for proxy in self.proxies}
        for row, profile in enumerate(recent):
            proxy = proxy_by_url.get(profile.proxy or "")
            values = (
                profile.name, profile.status,
                proxy.name if proxy else ("No proxy" if not profile.proxy else "Custom proxy"),
                (profile.last_used_at or "Never").replace("T", " ")[:16],
            )
            for column, value in enumerate(values): self._set_item(self.dashboard_recent, row, column, value, column == 0)
            self.dashboard_recent.setCellWidget(row, 4, self._menu_button([("Open", partial(self.open_profile_by_id, profile.id)), ("Edit", partial(self.edit_profile_by_id, profile.id))]))

    def _save_proxy_pool_settings(self, *_args) -> None:
        if not hasattr(self, "proxy_pool_enabled"):
            return
        self.config_store.set_proxy_pool_enabled(self.proxy_pool_enabled.isChecked())
        self.config_store.set_proxy_pool_interval_minutes(int(self.proxy_pool_interval.currentData() or 30))
        self.show_status("Smart Proxy Pool settings saved")

    def _task_started(self, task_id: str, title: str, detail: str) -> None:
        self.task_center.add_task(title, detail, task_id)

    def _task_progress(self, task_id: str, progress: int, detail: str) -> None:
        self.task_center.update_task(task_id, progress=progress, detail=detail)

    def _task_finished(self, task_id: str, success: bool, detail: str) -> None:
        if success: self.task_center.finish_task(task_id, detail)
        else: self.task_center.fail_task(task_id, detail)

    def _install_shortcuts(self) -> None:
        self._shortcuts = []
        for sequence, callback in (
            ("Ctrl+N", self.create_profile), ("Ctrl+Shift+N", self.create_profiles_batch),
            ("Ctrl+F", self.focus_profile_search), ("Ctrl+K", self.open_command_palette),
            ("Ctrl+Enter", self.open_selected_profiles), ("Ctrl+R", self.open_selected_profiles),
            ("Ctrl+H", self.check_selected_profiles), ("Ctrl+Shift+B", self.bulk_edit_selected_profiles),
            ("Ctrl+Z", self._undo_last_action), ("Ctrl+1", partial(self.pages.setCurrentIndex, PAGE_DASHBOARD)),
            ("Ctrl+2", partial(self.pages.setCurrentIndex, PAGE_PROFILES)),
            ("Ctrl+,", partial(self.pages.setCurrentIndex, PAGE_SETTINGS)),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self); shortcut.activated.connect(callback); self._shortcuts.append(shortcut)
        for sequence, callback in (("Delete", self.delete_selected_profiles), ("F2", self.rename_current_profile)):
            shortcut = QShortcut(QKeySequence(sequence), self.profile_table)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut); shortcut.activated.connect(callback); self._shortcuts.append(shortcut)

    def focus_profile_search(self) -> None:
        self.pages.setCurrentIndex(PAGE_PROFILES); self.search_input.setFocus(); self.search_input.selectAll()

    def rename_current_profile(self) -> None:
        row = self.profile_table.currentRow()
        if row < 0 or row >= len(self.profile_table.profiles):
            return
        profile = self.profile_table.profiles[row]
        name, accepted = QInputDialog.getText(self, tr("Rename profile"), tr("Profile name"), text=profile.name)
        if accepted and name.strip(): self.rename_profile(profile.id, name.strip())

    def _page_changed(self, page: int) -> None:
        if page != PAGE_EDITOR:
            self.config_store.set_last_page(page)
        self._sync_nav_selection(page)
        if page == PAGE_DASHBOARD: self._refresh_dashboard()

    def _sync_nav_selection(self, page: int) -> None:
        matched = False
        for button in self._nav_buttons:
            should_check = not matched and int(button.property("pageIndex")) == page
            button.setChecked(should_check)
            matched = matched or should_check

    def toggle_sidebar(self) -> None:
        self._set_sidebar_collapsed(not self._sidebar_collapsed)

    def _set_sidebar_collapsed(self, collapsed: bool, persist: bool = True) -> None:
        if not hasattr(self, "sidebar"):
            return
        self._sidebar_collapsed = bool(collapsed)
        self.sidebar.setFixedWidth(74 if collapsed else 220)
        self.brand_labels_widget.setVisible(not collapsed)
        self.sidebar_toggle.setText("›" if collapsed else "‹")
        self.sidebar_toggle.setToolTip("Expand sidebar" if collapsed else "Collapse sidebar")
        for button in self._nav_buttons:
            label = str(button.property("fullLabel"))
            button.setText("" if collapsed else label)
            button.setToolTip(label if collapsed else "")
            button.setProperty("collapsed", collapsed)
            button.style().unpolish(button)
            button.style().polish(button)
        if persist: self.config_store.set_sidebar_collapsed(collapsed)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "sidebar") and self.width() < 1180 and not self._sidebar_collapsed:
            self._set_sidebar_collapsed(True, persist=False)
        self._position_toast()

    def show_error(self, message: str) -> None:
        message = tr(message)
        QMessageBox.critical(self, tr("Error"), message); self.statusBar().showMessage(message, 8000)

    def show_status(self, message: str) -> None:
        text = tr(message)
        self.statusBar().showMessage(text, 6000)
        self._show_toast(text)

    def _show_toast(self, message: str) -> None:
        if not hasattr(self, "toast_label"):
            return
        self.toast_label.setText(message)
        self.toast_label.adjustSize()
        self.toast_label.setFixedWidth(min(max(self.toast_label.sizeHint().width() + 20, 260), 520))
        self.toast_label.setFixedHeight(max(42, self.toast_label.sizeHint().height() + 16))
        self._position_toast()
        self.toast_label.raise_()
        self.toast_label.show()
        QTimer.singleShot(3600, self.toast_label.hide)

    def _position_toast(self) -> None:
        if not hasattr(self, "toast_label"):
            return
        margin = 18
        self.toast_label.move(
            max(margin, self.width() - self.toast_label.width() - margin),
            margin + 10,
        )

    def closeEvent(self, event) -> None:
        self._flush_column_widths()
        if self._update_check_thread is not None or self._update_download_thread is not None:
            QMessageBox.information(
                self, tr("App updates"),
                tr("Please wait for the current update operation to finish."),
            )
            event.ignore(); return
        if self._allow_close or not self.controller.has_background_work():
            event.accept(); return
        if QMessageBox.question(
            self, "Exit", "Background checks or browsers are active. Stop and exit?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            event.ignore(); return
        event.ignore(); self.setEnabled(False); self.controller.shutdown(); QTimer.singleShot(250, self._finish_close)

    def _finish_close(self) -> None:
        if self.controller.has_background_work():
            QTimer.singleShot(250, self._finish_close); return
        self._allow_close = True; self.close()
