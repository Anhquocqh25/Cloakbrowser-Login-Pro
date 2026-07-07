import sys

from pathlib import Path

import os


# PyInstaller's windowed bootloader intentionally sets stdout/stderr to None.
# CloakBrowser and a few dependencies still write informational messages to
# those streams, so provide valid sinks before importing the browser stack.
_windowed_streams = []
for _stream_name in ("stdout", "stderr"):
    if getattr(sys, _stream_name, None) is None:
        _stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, _stream_name, _stream)
        _windowed_streams.append(_stream)

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from config import APP_NAME
from controllers.profile_controller import ProfileController
from database.db import initialize_database
from database.profile_repository import ProfileRepository
from storage.config_store import ConfigStore
from ui.main_window import MainWindow
from utils.i18n import install_i18n, set_language


def main() -> int:
    startup_report = initialize_database()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    project_dir = Path(__file__).resolve().parent
    icon_path = project_dir / "assets" / "app_logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")
    available_fonts = set(QFontDatabase.families())
    font_family = "Segoe UI" if "Segoe UI" in available_fonts else ("Arial" if "Arial" in available_fonts else "Tahoma")
    app.setFont(QFont(font_family, 10))
    stylesheet_path = project_dir / "ui" / "styles.qss"
    app.setStyleSheet(stylesheet_path.read_text(encoding="utf-8"))

    repository = ProfileRepository()
    config_store = ConfigStore()
    set_language(config_store.language())
    app._i18n_filter = install_i18n(app)
    controller = ProfileController(repository, config_store=config_store)
    window = MainWindow(controller, config_store)
    window.show()
    if startup_report.recovered_anything:
        total = startup_report.recovered_profiles + startup_report.recovered_deleted_profiles
        message = (
            f"Recovered {total} profile(s) from existing browser data.\n\n"
            "The app found browser profile folders that were not listed in app.db, "
            "so it restored them automatically. Please review proxy, OS and fingerprint settings "
            "for any profile restored without an existing profile.json sidecar."
        )
        QTimer.singleShot(400, lambda: QMessageBox.information(window, "Profile recovery", message))
        QTimer.singleShot(450, lambda: window.show_status(f"Recovered {total} profile(s) from local data"))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
