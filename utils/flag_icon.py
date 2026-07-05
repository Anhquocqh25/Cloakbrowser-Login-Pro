from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


FLAGS_DIR = Path(__file__).resolve().parent.parent / "assets" / "flags"


@lru_cache(maxsize=300)
def country_flag_pixmap(country_code: str, width: int = 24, height: int = 18) -> QPixmap:
    code = str(country_code or "").strip().lower()
    path = FLAGS_DIR / f"{code}.svg"
    if len(code) != 2 or not path.is_file():
        return QPixmap()
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QPixmap()
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return pixmap


def country_flag_icon(country_code: str) -> QIcon:
    pixmap = country_flag_pixmap(country_code)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()
