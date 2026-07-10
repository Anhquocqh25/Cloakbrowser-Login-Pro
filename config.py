from pathlib import Path

import os

APP_NAME = "CloakBrowser Login"
APP_VERSION = "0.1.4"
APP_BASE_DIR = Path(os.environ.get("CLOAK_LOGIN_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME))
PROFILE_STORAGE_DIR = APP_BASE_DIR / "profiles"
EXTENSION_STORAGE_DIR = APP_BASE_DIR / "extensions"
DATABASE_PATH = APP_BASE_DIR / "app.db"
BACKUP_STORAGE_DIR = APP_BASE_DIR / "backups"

DEFAULT_TIMEZONE = "Asia/Bangkok"
DEFAULT_LOCALE = "en-US"
DEFAULT_SCREEN_WIDTH = 1200
DEFAULT_SCREEN_HEIGHT = 800
