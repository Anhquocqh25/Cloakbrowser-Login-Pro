from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


ICON_PATHS: dict[str, str] = {
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    "profiles": '<path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9.5" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "profile": '<circle cx="12" cy="8" r="4"/><path d="M6 21v-2a6 6 0 0 1 12 0v2"/>',
    "proxy": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/>',
    "startup": '<path d="M7 17 17 7"/><path d="M8 7h9v9"/><rect x="4" y="4" width="16" height="16" rx="2"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/>',
    "backup": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6"/><path d="M12 7v5l3 2"/>',
    "health": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-5"/>',
    "activity": '<path d="M4 6h16"/><path d="M4 12h10"/><path d="M4 18h16"/>',
    "fingerprint": '<path d="M12 11c0 2.2-1 4-2.7 5.2"/><path d="M14.8 16.2c.8-1.4 1.2-3.1 1.2-5.2a4 4 0 0 0-8 0"/><path d="M18.3 19.1c1.1-2 1.7-4.7 1.7-8.1a8 8 0 0 0-16 0"/><path d="M6.6 18.5C7.6 17.4 8 15 8 11"/><path d="M12 3a8 8 0 0 1 8 8"/><path d="M4 15.5c.7-1 1-2.5 1-4.5a7 7 0 0 1 14 0"/>',
    "tasks": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06A2 2 0 1 1 7.03 3.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.43.23.8.58 1 1 .28.47.72.6 1.1.6H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.4z"/>',
    "extensions": '<path d="M8.5 3a2.5 2.5 0 0 1 5 0v3H17a2 2 0 0 1 2 2v3.5h-3a2.5 2.5 0 0 0 0 5h3V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3.5h3a2.5 2.5 0 0 0 0-5H4V8a2 2 0 0 1 2-2h2.5z"/>',
    "bookmarks": '<path d="M6 3h12a1 1 0 0 1 1 1v18l-7-4-7 4V4a1 1 0 0 1 1-1z"/>',
}


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, size: int) -> QPixmap:
    paths = ICON_PATHS.get(name, ICON_PATHS["dashboard"])
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24"
         fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
      {paths}
    </svg>
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter)
    painter.end()
    return pixmap


def sidebar_icon(name: str, size: int = 22) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pixmap(name, "#6b7280", size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap(name, "#2f73f6", size), QIcon.Normal, QIcon.On)
    icon.addPixmap(_pixmap(name, "#9ca3af", size), QIcon.Disabled, QIcon.Off)
    return icon
