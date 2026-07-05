from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QRectF, Signal, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from ui.profile_table import ColumnSpec


class EyeToggleButton(QToolButton):
    toggled_key = Signal(str, bool)

    def __init__(self, key: str, checked: bool, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(32, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda value: self.toggled_key.emit(self.key, value))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = self.rect().center()
        color = QColor("#20b89a" if self.isChecked() else "#9ca3af")
        painter.setPen(QPen(color, 1.4))
        eye = QRectF(center.x() - 8.5, center.y() - 5.5, 17.0, 11.0)
        painter.drawEllipse(eye)
        if self.isChecked():
            painter.setBrush(color)
            painter.drawEllipse(QRectF(center.x() - 2.2, center.y() - 2.2, 4.4, 4.4))
        else:
            painter.drawLine(center.x() - 10, center.y() + 8, center.x() + 10, center.y() - 8)


class ColumnSettingsDialog(QDialog):
    visibility_changed = Signal(list)

    GROUP_LABELS = {
        "Proxies": "Proxies",
        "Profile Notes": "Profile Notes",
        "Profile Info": "Profile Info",
        "Core": "Core",
    }
    GROUP_ORDER = ["Proxies", "Profile Notes", "Profile Info", "Core"]

    def __init__(
        self,
        columns: list[ColumnSpec],
        visible_keys: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self.visible = set(visible_keys)
        self.required = {spec.key for spec in columns if spec.required}
        self.visible.update(self.required)
        self.setWindowTitle("Column Settings")
        self.setModal(True)
        self.setMinimumSize(380, 540)
        self.resize(400, 570)
        self.setObjectName("columnSettingsDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 14)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("columnDialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 14, 12, 12)
        title = QLabel("Column Settings")
        title.setObjectName("columnDialogTitle")
        close = QPushButton("×")
        close.setObjectName("dialogCloseButton")
        close.setFixedSize(30, 30)
        close.clicked.connect(self.accept)
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(close)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("columnScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 12, 18, 12)
        content_layout.setSpacing(4)

        grouped: dict[str, list[ColumnSpec]] = defaultdict(list)
        for spec in columns:
            if not spec.required:
                grouped[spec.group].append(spec)

        for group in self.GROUP_ORDER:
            specs = grouped.get(group, [])
            if not specs:
                continue
            section = QLabel(self.GROUP_LABELS.get(group, group))
            section.setObjectName("columnGroupTitle")
            content_layout.addWidget(section)
            for spec in specs:
                row = QWidget()
                row.setObjectName("columnOptionRow")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(8, 3, 4, 3)
                label = QLabel(spec.label or spec.key.title())
                label.setObjectName("columnOptionLabel")
                eye = EyeToggleButton(spec.key, spec.key in self.visible)
                eye.toggled_key.connect(self._set_visible)
                row_layout.addWidget(label)
                row_layout.addStretch(1)
                row_layout.addWidget(eye)
                content_layout.addWidget(row)
            content_layout.addSpacing(12)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(20, 10, 20, 0)
        reset = QPushButton("Reset default")
        reset.setObjectName("columnResetButton")
        reset.clicked.connect(self._reset_defaults)
        done = QPushButton("Done")
        done.setObjectName("primaryButton")
        done.clicked.connect(self.accept)
        footer.addWidget(reset)
        footer.addStretch(1)
        footer.addWidget(done)
        root.addLayout(footer)

    def _set_visible(self, key: str, visible: bool) -> None:
        if visible:
            self.visible.add(key)
        else:
            self.visible.discard(key)
        self.visible.update(self.required)
        self.visibility_changed.emit(self.visible_keys())

    def _reset_defaults(self) -> None:
        self.visible = {spec.key for spec in self.columns if spec.default_visible or spec.required}
        self.visibility_changed.emit(self.visible_keys())
        self.accept()

    def visible_keys(self) -> list[str]:
        return [spec.key for spec in self.columns if spec.key in self.visible]
