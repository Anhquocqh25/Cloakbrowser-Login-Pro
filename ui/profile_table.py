from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QRectF, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHeaderView, QHBoxLayout, QLabel, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QToolButton, QWidget,
)

from models.profile import Profile
from models.proxy import ProxyRecord
from utils.flag_icon import country_flag_icon


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    key: str
    label: str
    group: str
    width: int
    default_visible: bool = False
    required: bool = False
    stretch: bool = False


PROFILE_COLUMNS = [
    ColumnSpec("select", "", "Core", 54, True, True),
    ColumnSpec("name", "Name", "Core", 205, True, True, True),
    ColumnSpec("pinned", "Pinned", "Core", 72, False),
    ColumnSpec("run", "", "Core", 90, True, True),
    ColumnSpec("actions", "Actions", "Core", 76, True),
    ColumnSpec("state", "State", "Profile Notes", 116, True),
    ColumnSpec("notes", "Notes", "Profile Notes", 235, True, stretch=True),
    ColumnSpec("group_name", "Group", "Profile Notes", 135, True),
    ColumnSpec("tags", "Tags", "Profile Notes", 150, True),
    ColumnSpec("proxy_location", "Proxy & Location", "Proxies", 210, True, stretch=True),
    ColumnSpec("proxy_username", "Proxy Username", "Proxies", 150, True),
    ColumnSpec("os", "OS", "Profile Info", 120, True),
    ColumnSpec("browser_version", "Browser Version", "Profile Info", 125, True),
    ColumnSpec("health", "Health", "Profile Info", 110, True),
    ColumnSpec("last_used", "Last used", "Profile Info", 150, False),
    ColumnSpec("proxy_type", "Proxy Type", "Proxies", 105),
    ColumnSpec("proxy_port", "Proxy Port", "Proxies", 95),
    ColumnSpec("proxy_password", "Proxy Password", "Proxies", 135),
    ColumnSpec("sharing", "Sharing", "Profile Info", 100),
]


class CompactRunButton(QPushButton):
    """DPI-safe GoLogin-style Run/Stop button."""

    def __init__(self, text: str, stop_style: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.stop_style = stop_style
        self.hovered = False
        self.setObjectName("compactRunButton")
        self.setStyleSheet(
            "QPushButton#compactRunButton { background: transparent; border: none; "
            "padding: 0px; margin: 0px; min-width: 50px; max-width: 50px; "
            "min-height: 28px; max-height: 28px; }"
        )
        self.setFixedSize(50, 28)
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
            border, fill, text = "#d1d5db", "#f9fafb", "#9ca3af"
        elif self.stop_style:
            border, fill, text = "#ef9a9f", "#fff1f2" if self.hovered else "#ffffff", "#c2414b"
        else:
            border, fill, text = "#20b89a", "#eafaf6" if self.hovered else "#ffffff", "#0d8f78"
        painter.setPen(QPen(QColor(border), 1.15))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 6.0, 6.0)
        painter.setPen(QColor(text))
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


class ProfileTable(QTableWidget):
    run_requested = Signal(str)
    stop_requested = Signal(str)
    edit_requested = Signal(str)
    clone_requested = Signal(str)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)
    widths_changed = Signal(dict)
    checked_profiles_changed = Signal(list)
    metadata_updated = Signal(str, str, object)
    health_requested = Signal(str)
    export_requested = Signal(str)
    compatibility_requested = Signal(str)
    snapshot_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(PROFILE_COLUMNS), parent)
        self.profiles: list[Profile] = []
        self.proxy_records: list[ProxyRecord] = []
        self._checked_profile_ids: set[str] = set()
        self._updating = False
        self._layout_updating = False
        self.column_indexes = {spec.key: index for index, spec in enumerate(PROFILE_COLUMNS)}
        self._preferred_widths = {spec.key: spec.width for spec in PROFILE_COLUMNS}
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow_columns)

        self.setObjectName("profileTable")
        self.setHorizontalHeaderLabels([spec.label for spec in PROFILE_COLUMNS])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(52)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setTextElideMode(Qt.ElideRight)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumHeight(46)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(38)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.sectionResized.connect(self._section_resized)
        self.cellDoubleClicked.connect(self._start_inline_edit)
        self.itemChanged.connect(self._handle_item_changed)

        self._layout_updating = True
        try:
            for index, spec in enumerate(PROFILE_COLUMNS):
                self.setColumnWidth(index, spec.width)
        finally:
            self._layout_updating = False

    @property
    def default_visible_keys(self) -> list[str]:
        return [spec.key for spec in PROFILE_COLUMNS if spec.default_visible or spec.required]

    def set_proxy_records(self, records: list[ProxyRecord]) -> None:
        self.proxy_records = records
        if self.profiles:
            self.set_profiles(self.profiles)

    def set_profiles(self, profiles: list[Profile]) -> None:
        self._updating = True
        scroll_position = self.verticalScrollBar().value()
        self.profiles = list(profiles)
        self._checked_profile_ids.intersection_update(profile.id for profile in profiles)
        # Remove old cell widgets before recreating rows. During bulk start,
        # repeated replacements can otherwise remain pending and overlap.
        self.setRowCount(0)
        self.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            self._populate_row(row, profile)
        self.verticalScrollBar().setValue(scroll_position)
        self._updating = False
        self.checked_profiles_changed.emit(self.checked_profile_ids())

    def checked_profile_ids(self) -> list[str]:
        return [profile.id for profile in self.profiles if profile.id in self._checked_profile_ids]

    def set_all_checked(self, checked: bool) -> None:
        self._checked_profile_ids = {profile.id for profile in self.profiles} if checked else set()
        select_column = self.column_indexes["select"]
        for row in range(self.rowCount()):
            holder = self.cellWidget(row, select_column)
            checkbox = holder.findChild(QCheckBox) if holder else None
            if checkbox:
                checkbox.blockSignals(True)
                checkbox.setChecked(checked)
                checkbox.blockSignals(False)
        self.checked_profiles_changed.emit(self.checked_profile_ids())

    def clear_checked(self) -> None:
        self.set_all_checked(False)

    def _set_profile_checked(self, profile_id: str, checked: bool) -> None:
        if checked:
            self._checked_profile_ids.add(profile_id)
        else:
            self._checked_profile_ids.discard(profile_id)
        self.checked_profiles_changed.emit(self.checked_profile_ids())

    def set_visible_columns(self, visible_keys: list[str] | set[str]) -> None:
        visible = set(visible_keys)
        visible.update(spec.key for spec in PROFILE_COLUMNS if spec.required)
        for index, spec in enumerate(PROFILE_COLUMNS):
            self.setColumnHidden(index, spec.key not in visible)
        self._schedule_reflow()

    def apply_column_widths(self, widths: dict[str, int]) -> None:
        for spec in PROFILE_COLUMNS:
            if spec.key == "actions":
                self._preferred_widths[spec.key] = spec.width
                continue
            self._preferred_widths[spec.key] = max(
                spec.width, min(int(widths.get(spec.key, spec.width)), 520)
            )
        self._schedule_reflow()

    def current_column_widths(self) -> dict[str, int]:
        return dict(self._preferred_widths)

    def _section_resized(self, index: int, old_size: int, new_size: int) -> None:
        if self._layout_updating or self._updating or self.isColumnHidden(index):
            return
        spec = PROFILE_COLUMNS[index]
        delta = new_size - old_size
        preferred = max(spec.width, min(self._preferred_widths[spec.key] + delta, 520))
        self._preferred_widths[spec.key] = preferred
        self.widths_changed.emit(self.current_column_widths())
        self._schedule_reflow()

    def _schedule_reflow(self) -> None:
        self._reflow_timer.start(0)

    def _reflow_columns(self) -> None:
        visible = [
            (index, spec) for index, spec in enumerate(PROFILE_COLUMNS)
            if not self.isColumnHidden(index)
        ]
        available = max(0, self.viewport().width() - 2)
        if not visible or available <= 0:
            return
        widths = {
            index: max(spec.width, self._preferred_widths[spec.key])
            for index, spec in visible
        }
        extra = available - sum(widths.values())
        if extra > 0:
            stretchable = [(index, spec) for index, spec in visible if spec.stretch]
            if not stretchable:
                stretchable = [
                    (index, spec) for index, spec in visible if spec.key == "name"
                ] or [visible[-1]]
            share, remainder = divmod(extra, len(stretchable))
            for position, (index, _spec) in enumerate(stretchable):
                widths[index] += share + (1 if position < remainder else 0)

        self._layout_updating = True
        try:
            for index, width in widths.items():
                self.setColumnWidth(index, width)
        finally:
            self._layout_updating = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_reflow()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_reflow()

    def _set_item(self, row: int, key: str, text: str, *, editable: bool = False, bold: bool = False) -> None:
        item = QTableWidgetItem(text or "—")
        item.setData(Qt.UserRole, self.profiles[row].id)
        item.setToolTip(text or "—")
        flags = item.flags()
        item.setFlags(flags | Qt.ItemIsEditable if editable else flags & ~Qt.ItemIsEditable)
        if bold:
            item.setFont(QFont(self.font().family(), 10, QFont.DemiBold))
        self.setItem(row, self.column_indexes[key], item)

    def _populate_row(self, row: int, profile: Profile) -> None:
        parsed = urlparse(profile.proxy or "")
        proxy_record = next((record for record in self.proxy_records if record.url == profile.proxy), None)
        platform = {"windows": "Windows 11", "macos": "macOS", "linux": "Linux"}.get(profile.platform, profile.platform)
        proxy_address = ""
        if profile.proxy:
            host = parsed.hostname or "Unknown host"
            host = f"[{host}]" if ":" in host else host
            proxy_address = f"{host}:{parsed.port}" if parsed.port else host
        proxy_location = "No proxy"
        if profile.proxy:
            label_parts = [proxy_address]
            if proxy_record and proxy_record.location:
                label_parts.append(proxy_record.location)
            proxy_location = " · ".join(label_parts)
        if proxy_record and profile.proxy:
            health = {
                "live": "Live", "dead": "Dead", "checking": "Checking",
                "unknown": "Not checked",
            }.get(proxy_record.status, proxy_record.status.title())
            proxy_location = f"{proxy_location} · {health}"
        proxy_type = (parsed.scheme or "—").upper()
        username = unquote(parsed.username or "")
        password = "••••••" if parsed.password else "—"
        port = str(parsed.port or "—")

        select = QCheckBox()
        select.setObjectName("rowCheckbox")
        select.setChecked(profile.id in self._checked_profile_ids)
        select.toggled.connect(partial(self._set_profile_checked, profile.id))
        self.setCellWidget(row, self.column_indexes["select"], self._centered(select))
        self._set_item(row, "name", profile.name, editable=True, bold=True)
        self.item(row, self.column_indexes["name"]).setIcon(self._avatar_icon(profile))
        self._set_item(row, "pinned", "★" if profile.pinned else "—")
        self.setCellWidget(row, self.column_indexes["run"], self._run_widget(profile))
        self.setCellWidget(row, self.column_indexes["actions"], self._actions_widget(profile))
        self.setCellWidget(row, self.column_indexes["state"], self._state_widget(profile.status))
        self._set_item(row, "notes", profile.notes or "Click to add notes", editable=True)
        self._set_item(row, "group_name", profile.group_name or "—", editable=True)
        self._set_item(row, "tags", profile.tags or "—", editable=True)
        self._set_item(row, "proxy_location", proxy_location)
        if proxy_record and proxy_record.country_code:
            self.item(row, self.column_indexes["proxy_location"]).setIcon(
                country_flag_icon(proxy_record.country_code)
            )
        self._set_item(row, "proxy_username", username or "—")
        self._set_item(row, "os", platform)
        self._set_item(row, "browser_version", "System Chrome" if profile.browser_engine == "chrome" else "146")
        health_label = {"pass": "Healthy", "warning": "Attention", "fail": "Failed", "unknown": "Not checked"}.get(profile.health_status, profile.health_status)
        self._set_item(row, "health", health_label)
        self._set_item(row, "last_used", profile.last_used_at.replace("T", " ")[:16] if profile.last_used_at else "Never")
        self._set_item(row, "proxy_type", proxy_type)
        self._set_item(row, "proxy_port", port)
        self._set_item(row, "proxy_password", password)
        self._set_item(row, "sharing", "Private")

    @staticmethod
    def _avatar_icon(profile: Profile) -> QIcon:
        palette = ("#20b89a", "#4f7cff", "#8b5cf6", "#e8795a", "#d69e2e", "#0ea5b7")
        color = QColor(palette[sum(profile.id.encode("utf-8")) % len(palette)])
        pixmap = QPixmap(28, 28); pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap); painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen); painter.setBrush(color); painter.drawEllipse(2, 2, 24, 24)
        painter.setPen(QColor("#ffffff")); font = painter.font(); font.setBold(True); font.setPointSize(9); painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, (profile.name.strip()[:1] or "?").upper()); painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _centered(widget: QWidget, left: int = 4, right: int = 4) -> QWidget:
        holder = QWidget()
        holder.setObjectName("cellHolder")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(left, 3, right, 3)
        layout.addWidget(widget, 0, Qt.AlignCenter)
        return holder

    def _run_widget(self, profile: Profile) -> QWidget:
        running = profile.status in ("running", "stopping")
        waiting = profile.status in ("checking", "starting")
        button = CompactRunButton("Stop" if running else ("Wait" if waiting else "Run"), running)
        button.setEnabled(profile.status not in ("checking", "starting", "stopping"))
        button.clicked.connect(partial((self.stop_requested if running else self.run_requested).emit, profile.id))
        return self._centered(button, 6, 6)

    def _actions_widget(self, profile: Profile) -> QWidget:
        holder = QWidget()
        holder.setObjectName("cellHolder")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(0)
        more = QToolButton()
        more.setObjectName("rowMoreButton")
        more.setText("...")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Unpin" if profile.pinned else "Pin", partial(self.metadata_updated.emit, profile.id, "pinned", not profile.pinned))
        menu.addAction("Edit profile", partial(self.edit_requested.emit, profile.id))
        menu.addAction("Check profile", partial(self.health_requested.emit, profile.id))
        menu.addAction("Compatibility report", partial(self.compatibility_requested.emit, profile.id))
        menu.addAction("Fingerprint snapshot", partial(self.snapshot_requested.emit, profile.id))
        menu.addAction("Export profile", partial(self.export_requested.emit, profile.id))
        menu.addAction("Safe clone", partial(self.clone_requested.emit, profile.id))
        menu.addSeparator()
        menu.addAction("Move to Trash", partial(self.delete_requested.emit, profile.id))
        more.setMenu(menu)
        layout.addStretch(1)
        layout.addWidget(more, 0, Qt.AlignCenter)
        layout.addStretch(1)
        return holder

    def _state_widget(self, status: str) -> QWidget:
        mapping = {
            "running": ("●", "running", "#20b89a"),
            "checking": ("●", "checking proxy", "#f59e0b"),
            "starting": ("●", "starting", "#f59e0b"),
            "stopping": ("●", "stopping", "#f59e0b"),
            "stopped": ("○", "ready", "#9ca3af"),
        }
        dot, label, color = mapping.get(status, ("○", status, "#9ca3af"))
        widget = QWidget()
        widget.setObjectName("cellHolder")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(7, 3, 3, 3)
        layout.setSpacing(8)
        dot_label = QLabel(dot)
        dot_label.setStyleSheet(f"color: {color}; background: transparent;")
        text_label = QLabel(label)
        text_label.setObjectName("stateText")
        layout.addWidget(dot_label)
        layout.addWidget(text_label)
        layout.addStretch(1)
        return widget

    def _start_inline_edit(self, row: int, column: int) -> None:
        if column in {
            self.column_indexes["name"], self.column_indexes["notes"],
            self.column_indexes["group_name"], self.column_indexes["tags"],
        }:
            item = self.item(row, column)
            if item:
                self.editItem(item)

    def _handle_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        profile_id = str(item.data(Qt.UserRole) or "")
        value = item.text().strip()
        if not profile_id:
            return
        key_by_column = {
            self.column_indexes["name"]: "name",
            self.column_indexes["notes"]: "notes",
            self.column_indexes["group_name"]: "group_name",
            self.column_indexes["tags"]: "tags",
        }
        field = key_by_column.get(item.column())
        if field == "name" and value:
            self.rename_requested.emit(profile_id, value)
        elif field:
            self.metadata_updated.emit(profile_id, field, "" if value == "—" else value)
