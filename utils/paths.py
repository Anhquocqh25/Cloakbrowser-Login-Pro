from pathlib import Path

from config import APP_BASE_DIR, EXTENSION_STORAGE_DIR, PROFILE_STORAGE_DIR


def ensure_app_directories() -> None:
    APP_BASE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    EXTENSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def profile_user_data_dir(profile_id: str) -> Path:
    ensure_app_directories()
    return PROFILE_STORAGE_DIR / profile_id
