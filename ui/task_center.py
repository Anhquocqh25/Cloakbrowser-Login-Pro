from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from utils.i18n import tr


@dataclass(slots=True)
class TaskEntry:
    id: str
    title: str
    status: str = "running"
    detail: str = ""
    progress: int = -1
    started_at: str = ""


class TaskCenterPage(QWidget):
    cancel_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.entries: dict[str, TaskEntry] = {}
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 24); root.setSpacing(14)
        header = QHBoxLayout(); labels = QVBoxLayout()
        title = QLabel(tr("Task center")); title.setObjectName("pageTitle")
        subtitle = QLabel(tr("Background operations, progress and recent results")); subtitle.setObjectName("pageSubtitle")
        labels.addWidget(title); labels.addWidget(subtitle); header.addLayout(labels); header.addStretch(1)
        clear = QPushButton(tr("Clear completed")); clear.clicked.connect(self.clear_completed); header.addWidget(clear)
        root.addLayout(header)
        self.table = QTableWidget(0, 5); self.table.setObjectName("dataTable")
        self.table.setHorizontalHeaderLabels([tr("Started"), tr("Task"), tr("Status"), tr("Progress"), tr("Details")])
        self.table.verticalHeader().setVisible(False); self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setShowGrid(False)
        header_view = self.table.horizontalHeader(); header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents); header_view.setSectionResizeMode(1, QHeaderView.Stretch); header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents); header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents); header_view.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

    def add_task(self, title: str, detail: str = "", task_id: str | None = None) -> str:
        task_id = task_id or str(uuid4())
        self.entries[task_id] = TaskEntry(task_id, title, "running", detail, -1, datetime.now().strftime("%H:%M:%S"))
        self._render(); return task_id

    def update_task(self, task_id: str, *, status: str | None = None, detail: str | None = None, progress: int | None = None) -> None:
        entry = self.entries.get(task_id)
        if not entry: return
        if status is not None: entry.status = status
        if detail is not None: entry.detail = detail
        if progress is not None: entry.progress = max(-1, min(100, int(progress)))
        self._render()

    def finish_task(self, task_id: str, detail: str = "") -> None:
        self.update_task(task_id, status="completed", detail=detail or None, progress=100)

    def fail_task(self, task_id: str, detail: str) -> None:
        self.update_task(task_id, status="failed", detail=detail)

    def add_message(self, title: str, detail: str = "", status: str = "completed") -> str:
        task_id = self.add_task(title, detail); self.update_task(task_id, status=status, progress=100 if status == "completed" else -1); return task_id

    def clear_completed(self) -> None:
        self.entries = {key: value for key, value in self.entries.items() if value.status == "running"}
        self._render()

    def _render(self) -> None:
        entries = list(self.entries.values())[::-1]
        self.table.setRowCount(len(entries))
        status_labels = {"running": tr("Running"), "completed": tr("Completed"), "failed": tr("Failed"), "cancelled": tr("Cancelled")}
        for row, entry in enumerate(entries):
            values = (entry.started_at, tr(entry.title), status_labels.get(entry.status, entry.status.title()), f"{entry.progress}%" if entry.progress >= 0 else "—", tr(entry.detail))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(row, column, item)
