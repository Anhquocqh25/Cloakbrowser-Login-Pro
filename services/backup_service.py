from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from config import (
    APP_BASE_DIR, APP_NAME, APP_VERSION, BACKUP_STORAGE_DIR, DATABASE_PATH,
    EXTENSION_STORAGE_DIR, PROFILE_STORAGE_DIR,
)
from database.db import get_connection
from models.profile import Profile
from utils.paths import profile_user_data_dir


class BackupError(RuntimeError):
    pass


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if root != target and root not in target.parents:
            raise BackupError("Backup contains an unsafe file path.")
    archive.extractall(destination)


def create_full_backup(destination: str | Path | None = None) -> Path:
    BACKUP_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(destination) if destination else BACKUP_STORAGE_DIR / f"cloak-backup-{timestamp}.zip"
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cloak-backup-") as temp_name:
        temp = Path(temp_name)
        snapshot = temp / "app.db"
        source = get_connection()
        output = sqlite3.connect(snapshot)
        try:
            source.backup(output)
        finally:
            output.close()
            source.close()
        manifest = {
            "application": APP_NAME,
            "version": APP_VERSION,
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            "format": 1,
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        partial = target.with_suffix(".zip.partial")
        partial.unlink(missing_ok=True)
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.write(temp / "manifest.json", "manifest.json")
            archive.write(snapshot, "database/app.db")
            config_file = APP_BASE_DIR / "ui_config.json"
            if config_file.exists():
                archive.write(config_file, "ui_config.json")
            for source_root, archive_root in (
                (PROFILE_STORAGE_DIR, "profiles"),
                (EXTENSION_STORAGE_DIR, "extensions"),
            ):
                if not source_root.exists():
                    continue
                for file_path in source_root.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, str(Path(archive_root) / file_path.relative_to(source_root)))
        partial.replace(target)
    return target


def restore_full_backup(source: str | Path) -> None:
    archive_path = Path(source)
    if not archive_path.is_file():
        raise BackupError("Backup file does not exist.")
    with tempfile.TemporaryDirectory(prefix="cloak-restore-") as temp_name:
        temp = Path(temp_name)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, temp)
        except zipfile.BadZipFile as error:
            raise BackupError("The selected file is not a valid backup.") from error
        manifest_path = temp / "manifest.json"
        source_db = temp / "database" / "app.db"
        if not manifest_path.exists() or not source_db.exists():
            raise BackupError("The backup is incomplete.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("application") != APP_NAME:
            raise BackupError("This backup was created by a different application.")
        restored = sqlite3.connect(source_db)
        live = get_connection()
        try:
            restored.backup(live)
        finally:
            live.close()
            restored.close()
        for source_dir, live_dir in (
            (temp / "profiles", PROFILE_STORAGE_DIR),
            (temp / "extensions", EXTENSION_STORAGE_DIR),
        ):
            shutil.rmtree(live_dir, ignore_errors=True)
            if source_dir.exists():
                shutil.copytree(source_dir, live_dir, dirs_exist_ok=True)
            else:
                live_dir.mkdir(parents=True, exist_ok=True)
        config_file = temp / "ui_config.json"
        if config_file.exists():
            shutil.copy2(config_file, APP_BASE_DIR / "ui_config.json")


def export_profile(profile: Profile, destination: str | Path) -> Path:
    target = Path(destination)
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(profile)
    payload["status"] = "stopped"
    payload["deleted_at"] = ""
    partial = target.with_suffix(".zip.partial")
    partial.unlink(missing_ok=True)
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("profile.json", json.dumps(payload, ensure_ascii=False, indent=2))
        data_dir = profile_user_data_dir(profile.id)
        if data_dir.exists():
            for file_path in data_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, str(Path("profile-data") / file_path.relative_to(data_dir)))
    partial.replace(target)
    return target


def read_imported_profile(source: str | Path, new_id: str, new_name: str) -> tuple[Profile, Path]:
    archive_path = Path(source)
    temp = Path(tempfile.mkdtemp(prefix="cloak-profile-import-"))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, temp)
        payload = json.loads((temp / "profile.json").read_text(encoding="utf-8"))
        allowed = set(Profile.__dataclass_fields__)
        payload = {key: value for key, value in payload.items() if key in allowed}
        payload.update({
            "id": new_id, "name": new_name, "status": "stopped", "deleted_at": "",
            "created_at": Profile.now_timestamp(), "updated_at": Profile.now_timestamp(),
        })
        return Profile(**payload), temp
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def finish_profile_import(temp: Path, profile_id: str) -> None:
    source_data = temp / "profile-data"
    destination = profile_user_data_dir(profile_id)
    destination.mkdir(parents=True, exist_ok=True)
    if source_data.exists():
        shutil.copytree(source_data, destination, dirs_exist_ok=True)
    shutil.rmtree(temp, ignore_errors=True)


def prune_backups(keep: int = 10) -> None:
    backups = sorted(BACKUP_STORAGE_DIR.glob("cloak-backup-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep):]:
        old.unlink(missing_ok=True)
