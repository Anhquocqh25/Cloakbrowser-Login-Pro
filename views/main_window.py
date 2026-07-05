from __future__ import annotations

from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QRectF, QSettings, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from config import APP_BASE_DIR, APP_VERSION
from controllers.profile_controller import ProfileController
from models.bookmark import BookmarkRecord
from models.extension import ExtensionRecord
from models.profile import Profile
from models.proxy import ProxyRecord
from views.manage_dialogs import BookmarkDialog, ColumnSettingsDialog, ProxyDialog
from views.profile_dialog import ProfileDialog


class CompactRunButton(QPushButton):
    """Small action button painted inside its bounds to avoid DPI clipping."""

    def __init__(self, text: str, stop_style: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.stop_style = stop_style
        self.hovered = False
        self.setFixedSize(52, 28)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)

        if not self.isEnabled():
            border, fill, text = "#cfd5dd", "#f7f8fa", "#a1a8b3"
        elif self.stop_style:
            border = "#e88890"
            fill = "#fdebed" if self.hovered else "#fff5f5"
            text = "#bf3540"
        else:
            border = "#35b9a6"
            fill = "#eaf9f6" if self.hovered else "#ffffff"
            text = "#078b78"

        painter.setPen(QPen(QColor(border), 1.2))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 6.0, 6.0)
        painter.setPen(QColor(text))
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class MainWindow(QMainWindow):
    PROFILE_COLUMNS = [
        ("name", "Name"), ("run", ""), ("state", "State"), ("notes", "Notes"),
        ("platform", "OS"), ("proxy_type", "Proxy Type"),
        ("proxy_location", "Proxy & Location"), ("locale", "Locale"),
        ("screen", "Screen"), ("fingerprint", "Fingerprint Seed"), ("actions", ""),
    ]
    DEFAULT_PROFILE_COLUMNS = {
        "name", "run", "state", "notes", "platform", "proxy_type", "proxy_location", "actions"
    }
    REQUIRED_PROFILE_COLUMNS = {"name", "run"}
    PROFILE_COLUMN_SECTIONS = [
        ("Cơ bản", [("name", "Name"), ("run", "Run / Stop"), ("state", "State")]),
        ("Thông tin profile", [("notes", "Notes"), ("platform", "OS / Platform"), ("locale", "Locale"), ("screen", "Screen size"), ("fingerprint", "Fingerprint seed")]),
        ("Proxy", [("proxy_type", "Proxy type"), ("proxy_location", "Proxy & location")]),
        ("Khác", [("actions", "Actions menu")]),
    ]

    def __init__(self, controller: ProfileController) -> None:
        super().__init__()
        self.controller = controller
        self.profiles: list[Profile] = []
        self.visible_profiles: list[Profile] = []
        self.proxies: list[ProxyRecord] = []
        self.extensions: list[ExtensionRecord] = []
        self.bookmarks: list[BookmarkRecord] = []
        self._allow_close = False
        self.settings = QSettings("CloakHQ", "CloakBrowser Login")
        self.profile_column_indexes = {key: index for index, (key, _label) in enumerate(self.PROFILE_COLUMNS)}

        self.setWindowTitle("CloakBrowser Login")
        self.resize(1480, 850)
        self.setMinimumSize(1120, 680)
        self._build_ui()
        self._connect_signals()
        self.controller.load_profiles()
        self.controller.load_proxies()
        self.controller.load_extensions()
        self.controller.load_bookmarks()

    def _build_ui(self) -> None:
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setCentralWidget(central)

        shell.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_profiles_page())
        self.pages.addWidget(self._build_proxies_page())
        self.pages.addWidget(self._build_extensions_page())
        self.pages.addWidget(self._build_bookmarks_page())
        self.pages.addWidget(self._build_settings_page())
        shell.addWidget(self.pages, 1)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Sẵn sàng")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(7)

        brand = QLabel("CloakBrowser")
        brand.setObjectName("brandTitle")
        subtitle = QLabel("Native Profile Manager")
        subtitle.setObjectName("brandSubtitle")
        layout.addWidget(brand)
        layout.addWidget(subtitle)
        layout.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = [
            ("Profiles", 0), ("Proxies", 1), ("Extensions", 2),
            ("Bookmarks", 3), ("Settings", 4),
        ]
        for label, index in nav_items:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setProperty("pageIndex", index)
            button.setMinimumHeight(40)
            button.clicked.connect(partial(self._switch_page, index))
            self.nav_group.addButton(button)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        layout.addStretch(1)
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("sidebarFooter")
        layout.addWidget(version)
        return sidebar

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)

    def _new_page(self, title: str, subtitle: str, action_text: str | None = None, action=None):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        header.addLayout(title_box)
        header.addStretch(1)
        if action_text and action:
            button = QPushButton(action_text)
            button.setObjectName("primaryButton")
            button.clicked.connect(action)
            header.addWidget(button)
        layout.addLayout(header)
        return page, layout

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("dataTable")
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(58)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.setTextElideMode(Qt.ElideRight)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.horizontalHeader().setMinimumHeight(48)
        return table

    def _build_profiles_page(self) -> QWidget:
        page, layout = self._new_page(
            "Profiles", "Quản lý các trình duyệt độc lập", "+ Tạo profile", self.create_profile
        )
        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("profileSearch")
        self.search_input.setPlaceholderText("Tìm theo tên, note, platform, proxy...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(340)
        all_profiles = QPushButton("All profiles")
        all_profiles.setObjectName("tabButton")
        all_profiles.setCheckable(True)
        all_profiles.setChecked(True)
        self.profile_count = QLabel("0 profiles")
        self.profile_count.setObjectName("profileCount")
        filters.addWidget(self.search_input)
        filters.addWidget(all_profiles)
        filters.addWidget(self.profile_count)
        filters.addStretch(1)
        refresh = QPushButton("Làm mới")
        refresh.setObjectName("quietButton")
        refresh.clicked.connect(self.controller.load_profiles)
        columns_button = QPushButton("Cột hiển thị")
        columns_button.setObjectName("columnButton")
        columns_button.clicked.connect(self.open_column_settings)
        filters.addWidget(columns_button)
        filters.addWidget(refresh)
        layout.addLayout(filters)

        self.profiles_table = self._make_table([label for _key, label in self.PROFILE_COLUMNS])
        header = self.profiles_table.horizontalHeader()
        for column in range(len(self.PROFILE_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for key in ("name", "notes", "proxy_location"):
            header.setSectionResizeMode(self.profile_column_indexes[key], QHeaderView.Stretch)
        fixed_widths = {
            "run": 76, "state": 122, "platform": 110, "proxy_type": 145,
            "locale": 95, "screen": 110, "fingerprint": 145, "actions": 58,
        }
        for key, width in fixed_widths.items():
            index = self.profile_column_indexes[key]
            header.setSectionResizeMode(index, QHeaderView.Fixed)
            self.profiles_table.setColumnWidth(index, width)
        self._apply_profile_column_visibility(self._load_visible_profile_columns())
        layout.addWidget(self.profiles_table, 1)
        return page

    def _build_proxies_page(self) -> QWidget:
        page, layout = self._new_page("Proxies", "Lưu và tái sử dụng proxy cho nhiều profile", "+ Thêm proxy", self.add_proxy)
        self.proxies_table = self._make_table(["Name", "Type", "Address", "Location", "Notes", ""])
        header = self.proxies_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.proxies_table.setColumnWidth(1, 100)
        self.proxies_table.setColumnWidth(5, 58)
        layout.addWidget(self.proxies_table, 1)
        return page

    def _build_extensions_page(self) -> QWidget:
        page, layout = self._new_page(
            "Extensions", "Extension bật sẽ được nạp mặc định cho mọi profile", "+ Thêm extension", self.add_extension
        )
        self.extensions_table = self._make_table(["Name", "Source", "Path", "Status", ""])
        header = self.extensions_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.extensions_table.setColumnWidth(1, 110)
        self.extensions_table.setColumnWidth(3, 110)
        self.extensions_table.setColumnWidth(4, 58)
        layout.addWidget(self.extensions_table, 1)
        return page

    def _build_bookmarks_page(self) -> QWidget:
        page, layout = self._new_page(
            "Bookmarks", "Tự đồng bộ lên bookmark bar khi mở profile", "+ Thêm bookmark", self.add_bookmark
        )
        self.bookmarks_table = self._make_table(["Title", "Folder", "URL", ""])
        header = self.bookmarks_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.bookmarks_table.setColumnWidth(3, 58)
        layout.addWidget(self.bookmarks_table, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page, layout = self._new_page("Settings", "Thông tin ứng dụng và thư mục dữ liệu")
        card = QFrame()
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(8)
        card_layout.addWidget(QLabel(f"Phiên bản: {APP_VERSION}"))
        path_title = QLabel("Dữ liệu profile")
        path_title.setObjectName("settingLabel")
        card_layout.addWidget(path_title)
        path_value = QLabel(str(APP_BASE_DIR))
        path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_value.setWordWrap(True)
        card_layout.addWidget(path_value)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _connect_signals(self) -> None:
        self.search_input.textChanged.connect(self.apply_filter)
        self.profiles_table.cellDoubleClicked.connect(self._edit_profile_row)
        self.controller.profiles_changed.connect(self.populate_profiles)
        self.controller.proxies_changed.connect(self.populate_proxies)
        self.controller.extensions_changed.connect(self.populate_extensions)
        self.controller.bookmarks_changed.connect(self.populate_bookmarks)
        self.controller.profile_opened.connect(self.on_profile_opened)
        self.controller.profile_closed.connect(self.on_profile_closed)
        self.controller.operation_failed.connect(self.show_error)
        self.controller.info_message.connect(self.show_status)

    def _load_visible_profile_columns(self) -> set[str]:
        stored = self.settings.value("profiles/visible_columns", "")
        if isinstance(stored, str) and stored:
            selected = {value for value in stored.split(",") if value in self.profile_column_indexes}
            return selected | self.REQUIRED_PROFILE_COLUMNS
        return set(self.DEFAULT_PROFILE_COLUMNS)

    def _apply_profile_column_visibility(self, visible_keys: set[str]) -> None:
        for key, index in self.profile_column_indexes.items():
            self.profiles_table.setColumnHidden(index, key not in visible_keys)

    def open_column_settings(self) -> None:
        dialog = ColumnSettingsDialog(
            self,
            self.PROFILE_COLUMN_SECTIONS,
            self._load_visible_profile_columns(),
            self.DEFAULT_PROFILE_COLUMNS,
            self.REQUIRED_PROFILE_COLUMNS,
        )
        if dialog.exec() != ColumnSettingsDialog.Accepted:
            return
        selected = dialog.selected_columns()
        ordered = [key for key, _label in self.PROFILE_COLUMNS if key in selected]
        self.settings.setValue("profiles/visible_columns", ",".join(ordered))
        self._apply_profile_column_visibility(selected)

    def _set_item(self, table: QTableWidget, row: int, column: int, text: str, bold: bool = False) -> None:
        item = QTableWidgetItem(text or "—")
        item.setToolTip(text or "—")
        if bold:
            item.setFont(QFont(self.font().family(), 10, QFont.DemiBold))
        table.setItem(row, column, item)

    def _menu_button(self, actions: list[tuple[str, object]]) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(3, 0, 8, 0)
        button = QToolButton()
        button.setObjectName("moreButton")
        button.setText("...")
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        for label, callback in actions:
            if label == "---":
                menu.addSeparator()
            else:
                menu.addAction(label, callback)
        button.setMenu(menu)
        layout.addWidget(button)
        return holder

    # Profiles
    def populate_profiles(self, profiles: list[Profile]) -> None:
        self.profiles = profiles
        self.apply_filter()

    def apply_filter(self) -> None:
        query = self.search_input.text().strip().lower()
        self.visible_profiles = [p for p in self.profiles if not query or query in " ".join([
            p.name, p.notes, p.platform, p.proxy or "", p.timezone, p.locale, p.status,
        ]).lower()]
        self.profiles_table.setRowCount(len(self.visible_profiles))
        self.profile_count.setText(f"{len(self.visible_profiles)} profiles")
        columns = self.profile_column_indexes
        for row, profile in enumerate(self.visible_profiles):
            self._set_item(self.profiles_table, row, columns["name"], profile.name, True)
            self.profiles_table.setCellWidget(row, columns["run"], self._run_button(profile))
            self.profiles_table.setCellWidget(row, columns["state"], self._status_label(profile.status))
            platform = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(profile.platform, profile.platform)
            notes = profile.notes or f"{platform} · {profile.locale} · {profile.screen_size_label}"
            self._set_item(self.profiles_table, row, columns["notes"], notes)
            self._set_item(self.profiles_table, row, columns["platform"], platform)
            self._set_item(self.profiles_table, row, columns["proxy_type"], self._proxy_type(profile))
            self._set_item(self.profiles_table, row, columns["proxy_location"], self._proxy_location(profile))
            self._set_item(self.profiles_table, row, columns["locale"], profile.locale)
            self._set_item(self.profiles_table, row, columns["screen"], profile.screen_size_label)
            self._set_item(self.profiles_table, row, columns["fingerprint"], str(profile.fingerprint_seed or "—"))
            self.profiles_table.setCellWidget(row, columns["actions"], self._menu_button([
                ("Chỉnh sửa", partial(self.edit_profile_by_id, profile.id)),
                ("Nhân bản", partial(self.clone_profile_by_id, profile.id)),
                ("---", None),
                ("Xóa", partial(self.delete_profile_by_id, profile.id)),
            ]))

    def _run_button(self, profile: Profile) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(8, 5, 8, 5)
        running = profile.status in ("running", "stopping")
        button = CompactRunButton("Stop" if running else "Run", stop_style=running)
        button.setEnabled(profile.status not in ("starting", "stopping"))
        button.clicked.connect(partial(self.close_profile_by_id if running else self.open_profile_by_id, profile.id))
        layout.addWidget(button, 0, Qt.AlignCenter)
        return holder

    def _status_label(self, status: str) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(5, 0, 2, 0)
        mapping = {
            "running": ("●  running", "runningStatus"), "starting": ("●  starting", "busyStatus"),
            "stopping": ("●  stopping", "busyStatus"), "stopped": ("○  ready", "readyStatus"),
        }
        text, name = mapping.get(status, (status, "readyStatus"))
        label = QLabel(text)
        label.setObjectName(name)
        layout.addWidget(label)
        return holder

    @staticmethod
    def _proxy_type(profile: Profile) -> str:
        if not profile.proxy:
            return "—"
        return f"Proxy · {urlparse(profile.proxy).scheme.upper() or 'HTTP'}"

    @staticmethod
    def _proxy_location(profile: Profile) -> str:
        if not profile.proxy:
            return "Direct connection"
        return "Auto-match proxy" if profile.auto_geoip else profile.timezone

    def _profile_dialog(self, profile=None) -> ProfileDialog:
        return ProfileDialog(self, profile=profile, proxies=self.proxies)

    def create_profile(self) -> None:
        dialog = self._profile_dialog()
        if dialog.exec() == ProfileDialog.Accepted:
            try: self.controller.create_profile(**dialog.get_payload())
            except Exception as error: self.show_error(str(error))

    def edit_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile:
            return self.show_error("Profile không tồn tại.")
        dialog = self._profile_dialog(profile)
        if dialog.exec() == ProfileDialog.Accepted:
            try: self.controller.update_profile(profile.id, **dialog.get_payload())
            except Exception as error: self.show_error(str(error))

    def _edit_profile_row(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.visible_profiles): self.edit_profile_by_id(self.visible_profiles[row].id)

    def clone_profile_by_id(self, profile_id: str) -> None:
        try: self.controller.clone_profile(profile_id)
        except Exception as error: self.show_error(str(error))

    def open_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if not profile: return self.show_error("Profile không tồn tại.")
        if not profile.proxy:
            answer = QMessageBox.warning(self, "Profile chưa có proxy", "Profile sẽ dùng cùng IP với máy. Bạn vẫn muốn mở?", QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes: return
        try: self.controller.open_profile(profile.id)
        except Exception as error: self.show_error(str(error))

    def close_profile_by_id(self, profile_id: str) -> None:
        try: self.controller.close_profile(profile_id)
        except Exception as error: self.show_error(str(error))

    def delete_profile_by_id(self, profile_id: str) -> None:
        profile = self.controller.get_profile(profile_id)
        if profile and QMessageBox.question(self, "Xóa profile", f"Xóa {profile.name}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try: self.controller.delete_profile(profile_id)
            except Exception as error: self.show_error(str(error))

    # Proxies
    def populate_proxies(self, records: list[ProxyRecord]) -> None:
        self.proxies = records
        self.proxies_table.setRowCount(len(records))
        for row, record in enumerate(records):
            parsed = urlparse(record.url)
            address = f"{parsed.hostname or ''}:{parsed.port or ''}".rstrip(":")
            self._set_item(self.proxies_table, row, 0, record.name, True)
            self._set_item(self.proxies_table, row, 1, record.proxy_type)
            self._set_item(self.proxies_table, row, 2, address)
            self._set_item(self.proxies_table, row, 3, record.location)
            self._set_item(self.proxies_table, row, 4, record.notes)
            self.proxies_table.setCellWidget(row, 5, self._menu_button([
                ("Chỉnh sửa", partial(self.edit_proxy, record)), ("---", None),
                ("Xóa", partial(self.delete_proxy, record)),
            ]))

    def add_proxy(self) -> None:
        self.edit_proxy(None)

    def edit_proxy(self, record: ProxyRecord | None) -> None:
        dialog = ProxyDialog(self, record)
        if dialog.exec() == ProxyDialog.Accepted:
            try: self.controller.save_proxy(**dialog.payload())
            except Exception as error: self.show_error(str(error))

    def delete_proxy(self, record: ProxyRecord) -> None:
        if QMessageBox.question(self, "Xóa proxy", f"Xóa {record.name}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.controller.delete_proxy(record.id)

    # Extensions
    def populate_extensions(self, records: list[ExtensionRecord]) -> None:
        self.extensions = records
        self.extensions_table.setRowCount(len(records) + 1)
        self._set_item(self.extensions_table, 0, 0, "Default Bookmarks", True)
        self._set_item(self.extensions_table, 0, 1, "Built-in")
        self._set_item(self.extensions_table, 0, 2, "Managed by CloakBrowser Login")
        self._set_item(self.extensions_table, 0, 3, "Enabled")
        self.extensions_table.setCellWidget(0, 4, QWidget())
        for row, record in enumerate(records, start=1):
            self._set_item(self.extensions_table, row, 0, record.name, True)
            self._set_item(self.extensions_table, row, 1, "Unpacked")
            self._set_item(self.extensions_table, row, 2, record.path)
            self._set_item(self.extensions_table, row, 3, "Enabled" if record.enabled else "Disabled")
            self.extensions_table.setCellWidget(row, 4, self._menu_button([
                ("Tắt" if record.enabled else "Bật", partial(self.controller.toggle_extension, record.id)),
                ("---", None), ("Xóa", partial(self.controller.delete_extension, record.id)),
            ]))

    def add_extension(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục extension unpacked")
        if folder:
            try: self.controller.add_extension(folder)
            except Exception as error: self.show_error(str(error))

    # Bookmarks
    def populate_bookmarks(self, records: list[BookmarkRecord]) -> None:
        self.bookmarks = records
        self.bookmarks_table.setRowCount(len(records))
        for row, record in enumerate(records):
            self._set_item(self.bookmarks_table, row, 0, record.title, True)
            self._set_item(self.bookmarks_table, row, 1, record.folder)
            self._set_item(self.bookmarks_table, row, 2, record.url)
            self.bookmarks_table.setCellWidget(row, 3, self._menu_button([
                ("Chỉnh sửa", partial(self.edit_bookmark, record)), ("---", None),
                ("Xóa", partial(self.delete_bookmark, record)),
            ]))

    def add_bookmark(self) -> None:
        self.edit_bookmark(None)

    def edit_bookmark(self, record: BookmarkRecord | None) -> None:
        dialog = BookmarkDialog(self, record)
        if dialog.exec() == BookmarkDialog.Accepted:
            try: self.controller.save_bookmark(**dialog.payload())
            except Exception as error: self.show_error(str(error))

    def delete_bookmark(self, record: BookmarkRecord) -> None:
        if QMessageBox.question(self, "Xóa bookmark", f"Xóa {record.title}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try: self.controller.delete_bookmark(record.id)
            except Exception as error: self.show_error(str(error))

    def on_profile_opened(self, profile_id: str) -> None:
        self.show_status("Profile đang chạy")

    def on_profile_closed(self, profile_id: str) -> None:
        self.show_status("Profile đã dừng")

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Lỗi", message)
        self.statusBar().showMessage(message, 8000)

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def closeEvent(self, event) -> None:
        if self._allow_close or not self.controller.worker_threads:
            event.accept(); return
        answer = QMessageBox.question(self, "Đóng ứng dụng", "Đóng mọi browser và thoát?", QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            event.ignore(); return
        event.ignore()
        self.setEnabled(False)
        self.controller.shutdown()
        QTimer.singleShot(250, self._finish_close_when_ready)

    def _finish_close_when_ready(self) -> None:
        if self.controller.worker_threads:
            QTimer.singleShot(250, self._finish_close_when_ready); return
        self._allow_close = True
        self.close()
