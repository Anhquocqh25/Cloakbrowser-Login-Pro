from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from config import APP_BASE_DIR
from models.bookmark import BookmarkRecord
from models.extension import ExtensionRecord
from models.proxy import ProxyRecord
from ui.modern_controls import ModernComboBox
from utils.i18n import tr


class AdvancedFiltersDialog(QDialog):
    def __init__(
        self,
        groups: list[str],
        tags: list[str],
        current: dict[str, object],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("More profile filters"))
        self.setModal(True)
        self.resize(430, 390)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        title = QLabel(tr("More filters"))
        title.setObjectName("dialogTitle")
        subtitle = QLabel(tr("Keep the main toolbar compact and move less-used filters here."))
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(12)
        self.group_input = ModernComboBox()
        self.group_input.addItem(tr("All groups"), "")
        for group in groups:
            self.group_input.addItem(group, group)
        self.os_input = ModernComboBox()
        for label, value in (
            (tr("All systems"), ""), ("Windows 11", "windows"), ("macOS", "macos"), ("Linux", "linux")
        ):
            self.os_input.addItem(label, value)
        self.tag_input = ModernComboBox()
        self.tag_input.addItem(tr("All tags"), "")
        for tag in tags:
            self.tag_input.addItem(tag, tag)
        self.density_input = ModernComboBox()
        for label, value in ((tr("Comfortable"), "comfortable"), (tr("Compact"), "compact"), (tr("Wide"), "wide")):
            self.density_input.addItem(label, value)
        self.pinned_input = QCheckBox(tr("Pinned profiles only"))

        self.group_input.setCurrentIndex(max(0, self.group_input.findData(str(current.get("group") or ""))))
        self.os_input.setCurrentIndex(max(0, self.os_input.findData(str(current.get("platform") or ""))))
        self.tag_input.setCurrentIndex(max(0, self.tag_input.findData(str(current.get("tag") or ""))))
        self.density_input.setCurrentIndex(max(0, self.density_input.findData(str(current.get("density") or "comfortable"))))
        self.pinned_input.setChecked(bool(current.get("pinned")))

        for field in (self.group_input, self.os_input, self.tag_input, self.density_input):
            field.setMinimumHeight(36)
        form.addRow(tr("Group"), self.group_input)
        form.addRow(tr("Operating system"), self.os_input)
        form.addRow(tr("Tag"), self.tag_input)
        form.addRow(tr("Table density"), self.density_input)
        form.addRow("", self.pinned_input)
        root.addLayout(form)

        buttons = QHBoxLayout()
        reset = QPushButton(tr("Clear extra filters"))
        reset.clicked.connect(self.clear_filters)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        apply = QPushButton(tr("Apply filters"))
        apply.setObjectName("primaryButton")
        apply.clicked.connect(self.accept)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        root.addLayout(buttons)

    def clear_filters(self) -> None:
        self.group_input.setCurrentIndex(0)
        self.os_input.setCurrentIndex(0)
        self.tag_input.setCurrentIndex(0)
        self.density_input.setCurrentIndex(max(0, self.density_input.findData("comfortable")))
        self.pinned_input.setChecked(False)

    def filters(self) -> dict[str, object]:
        return {
            "group": str(self.group_input.currentData() or ""),
            "platform": str(self.os_input.currentData() or ""),
            "tag": str(self.tag_input.currentData() or ""),
            "density": str(self.density_input.currentData() or "comfortable"),
            "pinned": self.pinned_input.isChecked(),
        }


class OnboardingDialog(QDialog):
    def __init__(self, language: str, startup_url: str, has_profiles: bool, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("onboardingDialog")
        self.setWindowTitle(tr("Welcome to CloakBrowser Login"))
        self.setModal(True)
        self.resize(680, 470)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(16)

        self.step_label = QLabel()
        self.step_label.setObjectName("pageSubtitle")
        root.addWidget(self.step_label)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome_page())
        self.stack.addWidget(self._preferences_page(language, startup_url))
        self.stack.addWidget(self._ready_page(has_profiles))
        root.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.back_button = QPushButton(tr("Back")); self.back_button.clicked.connect(self._back)
        self.next_button = QPushButton(tr("Next")); self.next_button.setObjectName("primaryButton"); self.next_button.clicked.connect(self._next)
        skip = QPushButton(tr("Skip setup")); skip.clicked.connect(self.reject)
        buttons.addWidget(skip); buttons.addStretch(1); buttons.addWidget(self.back_button); buttons.addWidget(self.next_button)
        root.addLayout(buttons)
        self.stack.currentChanged.connect(self._refresh_buttons)
        self._refresh_buttons()

    def _page(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(4, 4, 4, 4); layout.setSpacing(14)
        title_label = QLabel(tr(title)); title_label.setObjectName("dialogTitle")
        text = QLabel(tr(description)); text.setObjectName("pageSubtitle"); text.setWordWrap(True)
        layout.addWidget(title_label); layout.addWidget(text)
        return page, layout

    def _welcome_page(self) -> QWidget:
        page, layout = self._page(
            "A clean start in three steps",
            "Configure the interface, review where profile data is stored, then create your first browser profile.",
        )
        for text in (
            "✓ Independent browser data for every profile",
            "✓ Proxy checks before launch",
            "✓ Fingerprint consistency and seed protection",
        ):
            label = QLabel(tr(text)); label.setObjectName("onboardingCheck"); layout.addWidget(label)
        layout.addStretch(1)
        return page

    def _preferences_page(self, language: str, startup_url: str) -> QWidget:
        page, layout = self._page("Basic preferences", "You can change these settings later.")
        form = QFormLayout(); form.setSpacing(12)
        self.language_input = ModernComboBox(); self.language_input.addItem("English", "en"); self.language_input.addItem("Tiếng Việt", "vi")
        self.language_input.setCurrentIndex(max(0, self.language_input.findData(language)))
        self.startup_input = QLineEdit(startup_url); self.startup_input.setPlaceholderText("https://example.com · optional")
        storage = QLabel(str(APP_BASE_DIR)); storage.setWordWrap(True); storage.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(tr("Interface language"), self.language_input)
        form.addRow(tr("Default startup website"), self.startup_input)
        form.addRow(tr("Profile data directory"), storage)
        layout.addLayout(form); layout.addStretch(1)
        return page

    def _ready_page(self, has_profiles: bool) -> QWidget:
        page, layout = self._page("Ready to work", "The dashboard will show profile, proxy and fingerprint health at a glance.")
        self.create_sample_input = QCheckBox(tr("Create a safe sample profile to explore the app"))
        self.create_sample_input.setChecked(not has_profiles)
        self.create_sample_input.setEnabled(not has_profiles)
        layout.addWidget(self.create_sample_input)
        hint = QLabel(tr("No browser will be opened automatically.")); hint.setObjectName("hintLabel"); hint.setWordWrap(True)
        layout.addWidget(hint); layout.addStretch(1)
        return page

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))

    def _next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.accept()
        else:
            self.stack.setCurrentIndex(self.stack.currentIndex() + 1)

    def _refresh_buttons(self, *_args) -> None:
        index = self.stack.currentIndex()
        self.step_label.setText(tr(f"Step {index + 1} of {self.stack.count()}"))
        self.back_button.setEnabled(index > 0)
        self.next_button.setText(tr("Finish") if index == self.stack.count() - 1 else tr("Next"))

    def payload(self) -> dict[str, Any]:
        return {
            "language": str(self.language_input.currentData() or "en"),
            "startup_url": self.startup_input.text().strip(),
            "create_sample": self.create_sample_input.isChecked(),
        }


class BulkEditDialog(QDialog):
    def __init__(
        self,
        count: int,
        proxies: list[ProxyRecord],
        extensions: list[ExtensionRecord],
        bookmarks: list[BookmarkRecord],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("bulkEditDialog")
        self.setWindowTitle(tr("Bulk edit profiles"))
        self.resize(680, 650)
        root = QVBoxLayout(self); root.setContentsMargins(24, 22, 24, 20); root.setSpacing(14)
        title = QLabel(tr(f"Edit {count} selected profiles")); title.setObjectName("dialogTitle")
        hint = QLabel(tr("Only enabled fields will be changed. A snapshot is kept for Undo.")); hint.setObjectName("hintLabel"); hint.setWordWrap(True)
        root.addWidget(title); root.addWidget(hint)

        form = QFormLayout(); form.setSpacing(10)
        self.group_enabled, self.group_input = self._field(QLineEdit())
        self.group_enabled.setText(tr("Group"))
        self.group_input.setPlaceholderText(tr("Example: Facebook US"))
        form.addRow(self.group_enabled, self.group_input)
        self.tags_enabled, self.tags_input = self._field(QLineEdit())
        self.tags_enabled.setText(tr("Tags"))
        self.tags_input.setPlaceholderText(tr("Comma-separated tags"))
        form.addRow(self.tags_enabled, self.tags_input)
        self.startup_enabled, self.startup_input = self._field(QLineEdit())
        self.startup_enabled.setText(tr("Startup website"))
        self.startup_input.setPlaceholderText("https://example.com · empty = global default")
        form.addRow(self.startup_enabled, self.startup_input)
        self.proxy_enabled = QCheckBox(tr("Proxy")); self.proxy_input = ModernComboBox(); self.proxy_input.setEnabled(False)
        self.proxy_enabled.toggled.connect(self.proxy_input.setEnabled)
        self.proxy_input.addItem(tr("No proxy"), "")
        self.proxy_input.addItem(tr("Best proxy from Smart Pool"), "__best__")
        for proxy in proxies:
            suffix = f" · {proxy.location}" if proxy.location else ""
            self.proxy_input.addItem(f"{proxy.name}{suffix}", proxy.url)
        form.addRow(self.proxy_enabled, self.proxy_input)
        root.addLayout(form)

        notes_row = QHBoxLayout()
        self.notes_enabled = QCheckBox(tr("Notes")); self.notes_mode = ModernComboBox(); self.notes_mode.addItem(tr("Append"), "append"); self.notes_mode.addItem(tr("Replace"), "replace")
        self.notes_input = QTextEdit(); self.notes_input.setFixedHeight(72)
        self.notes_mode.setEnabled(False); self.notes_input.setEnabled(False)
        self.notes_enabled.toggled.connect(self.notes_mode.setEnabled); self.notes_enabled.toggled.connect(self.notes_input.setEnabled)
        notes_row.addWidget(self.notes_enabled); notes_row.addWidget(self.notes_mode); notes_row.addStretch(1)
        root.addLayout(notes_row); root.addWidget(self.notes_input)

        resources = QHBoxLayout()
        self.extensions_enabled, self.extensions_list = self._check_list(tr("Extensions"), extensions)
        self.bookmarks_enabled, self.bookmarks_list = self._check_list(tr("Bookmarks"), bookmarks)
        resources.addWidget(self._list_card(self.extensions_enabled, self.extensions_list), 1)
        resources.addWidget(self._list_card(self.bookmarks_enabled, self.bookmarks_list), 1)
        root.addLayout(resources, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.accepted.connect(self._validate); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _field(editor: QWidget) -> tuple[QCheckBox, QWidget]:
        enabled = QCheckBox(); editor.setEnabled(False); enabled.toggled.connect(editor.setEnabled)
        return enabled, editor

    def _check_list(self, title: str, records: list[Any]) -> tuple[QCheckBox, QListWidget]:
        enabled = QCheckBox(title); listing = QListWidget(); listing.setEnabled(False); enabled.toggled.connect(listing.setEnabled)
        for record in records:
            item = QListWidgetItem(str(record.name if hasattr(record, "name") else record.title)); item.setData(Qt.UserRole, record.id); item.setCheckState(Qt.Checked)
            listing.addItem(item)
        return enabled, listing

    @staticmethod
    def _list_card(enabled: QCheckBox, listing: QListWidget) -> QFrame:
        card = QFrame(); card.setObjectName("settingsCard"); layout = QVBoxLayout(card); layout.setContentsMargins(10, 10, 10, 10); layout.addWidget(enabled); layout.addWidget(listing)
        return card

    def _validate(self) -> None:
        if not self.payload():
            QMessageBox.information(self, tr("Bulk edit profiles"), tr("Enable at least one field to change.")); return
        self.accept()

    @staticmethod
    def _checked_ids(listing: QListWidget) -> list[str]:
        return [str(listing.item(i).data(Qt.UserRole)) for i in range(listing.count()) if listing.item(i).checkState() == Qt.Checked]

    def payload(self) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if self.group_enabled.isChecked(): updates["group_name"] = self.group_input.text().strip()
        if self.tags_enabled.isChecked(): updates["tags"] = self.tags_input.text().strip()
        if self.startup_enabled.isChecked(): updates["startup_url"] = self.startup_input.text().strip()
        if self.proxy_enabled.isChecked(): updates["proxy"] = str(self.proxy_input.currentData() or "")
        if self.notes_enabled.isChecked(): updates["notes"] = self.notes_input.toPlainText().strip(); updates["notes_mode"] = str(self.notes_mode.currentData())
        if self.extensions_enabled.isChecked(): updates["extension_ids"] = self._checked_ids(self.extensions_list)
        if self.bookmarks_enabled.isChecked(): updates["bookmark_ids"] = self._checked_ids(self.bookmarks_list)
        return updates


class PresetChoiceDialog(QDialog):
    def __init__(self, presets: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Profile presets")); self.resize(620, 430)
        self.presets = [dict(item) for item in presets]; self.selected: dict[str, Any] | None = None
        root = QVBoxLayout(self); root.setContentsMargins(22, 20, 22, 18)
        title = QLabel(tr("Choose a reusable profile preset")); title.setObjectName("dialogTitle"); root.addWidget(title)
        self.listing = QListWidget(); self.listing.itemDoubleClicked.connect(lambda _item: self._use())
        root.addWidget(self.listing, 1)
        buttons = QHBoxLayout(); delete = QPushButton(tr("Delete preset")); delete.clicked.connect(self._delete); close = QPushButton(tr("Close")); close.clicked.connect(self.reject); use = QPushButton(tr("Use preset")); use.setObjectName("primaryButton"); use.clicked.connect(self._use)
        buttons.addWidget(delete); buttons.addStretch(1); buttons.addWidget(close); buttons.addWidget(use); root.addLayout(buttons)
        self._render()

    def _render(self) -> None:
        self.listing.clear()
        for index, preset in enumerate(self.presets):
            item = QListWidgetItem(f"{preset.get('name', 'Preset')}\n{preset.get('platform', 'windows')} · {preset.get('locale', 'en-US')} · {preset.get('screen_width', 1200)}x{preset.get('screen_height', 800)}")
            item.setData(Qt.UserRole, index); self.listing.addItem(item)
        if self.listing.count(): self.listing.setCurrentRow(0)

    def _use(self) -> None:
        item = self.listing.currentItem()
        if not item: return
        self.selected = dict(self.presets[int(item.data(Qt.UserRole))]); self.accept()

    def _delete(self) -> None:
        item = self.listing.currentItem()
        if not item: return
        self.presets.pop(int(item.data(Qt.UserRole))); self._render()


class CommandPaletteDialog(QDialog):
    def __init__(self, commands: list[tuple[str, str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Command palette")); self.resize(620, 450); self.command_key = ""
        self.commands = commands
        root = QVBoxLayout(self); root.setContentsMargins(18, 18, 18, 18)
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("Type a command…")); self.search.textChanged.connect(self._filter)
        self.listing = QListWidget(); self.listing.itemActivated.connect(lambda _item: self._choose())
        root.addWidget(self.search); root.addWidget(self.listing, 1)
        self._filter(""); self.search.setFocus()

    def _filter(self, query: str) -> None:
        self.listing.clear(); query = query.casefold().strip()
        for key, label, shortcut in self.commands:
            if query and query not in f"{label} {shortcut}".casefold(): continue
            item = QListWidgetItem(f"{tr(label)}\t{shortcut}"); item.setData(Qt.UserRole, key); self.listing.addItem(item)
        if self.listing.count(): self.listing.setCurrentRow(0)

    def _choose(self) -> None:
        item = self.listing.currentItem()
        if not item: return
        self.command_key = str(item.data(Qt.UserRole)); self.accept()
