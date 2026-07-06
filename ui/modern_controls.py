from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QComboBox, QListView, QStyle, QStyleOptionViewItem, QStyledItemDelegate


class ModernComboDelegate(QStyledItemDelegate):
    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self.combo = combo

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        current = index.row() == self.combo.currentIndex()
        hovered = bool(opt.state & QStyle.State_MouseOver)
        selected = bool(opt.state & QStyle.State_Selected) or current

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = opt.rect.adjusted(5, 3, -5, -3)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#eaf2ff"))
            painter.drawRoundedRect(rect, 7, 7)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#f6f8fb"))
            painter.drawRoundedRect(rect, 7, 7)

        text_rect = opt.rect.adjusted(14, 0, -38, 0)
        painter.setPen(QColor("#2f73f6" if current else "#374151"))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, str(index.data(Qt.DisplayRole) or ""))

        if current:
            check_rect = opt.rect.adjusted(opt.rect.width() - 31, 0, -13, 0)
            painter.setPen(QPen(QColor("#2f73f6"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            y = check_rect.center().y()
            painter.drawLine(check_rect.left(), y, check_rect.left() + 5, y + 5)
            painter.drawLine(check_rect.left() + 5, y + 5, check_rect.right(), y - 5)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(max(base.width(), 118), 34)


class ModernComboBox(QComboBox):
    """GoLogin-style dropdown with a soft popup and selected check mark.

    It intentionally keeps QComboBox's API, so existing screens can adopt it
    without changing profile/proxy logic.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("modernComboBox")
        self.setMinimumHeight(34)
        self.setMaxVisibleItems(12)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        view = QListView(self)
        view.setObjectName("modernComboPopup")
        view.setMouseTracking(True)
        view.setUniformItemSizes(False)
        view.setSpacing(2)
        view.setFrameShape(QListView.NoFrame)
        view.setVerticalScrollMode(QListView.ScrollPerPixel)
        view.setPalette(QPalette())
        self.setView(view)
        self.setItemDelegate(ModernComboDelegate(self))

    def showPopup(self) -> None:
        width = max(self.width(), self.view().sizeHintForColumn(0) + 52, 126)
        self.view().setMinimumWidth(width)
        self.view().setMaximumWidth(max(width, self.width()))
        super().showPopup()
