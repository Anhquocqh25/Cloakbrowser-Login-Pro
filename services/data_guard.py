from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from config import BACKUP_STORAGE_DIR, DATABASE_PATH, PROFILE_STORAGE_DIR
from models.profile import Profile
from services.profile_sidecar import profile_from_sidecar_or_directory, write_profile_sidecar
from utils.paths import ensure_app_directories


DB_BACKUP_DIR = BACKUP_STORAGE_DIR / "database"


@dataclass(slots=True)
class StartupRecoveryReport:
    database_backup: str = ""
    recovered_profiles: int = 0
    recovered_deleted_profiles: int = 0
    orphan_directories: list[str] | None = None

    @property
    def recovered_anything(self) -> bool:
        return self.recovered_profiles > 0 or self.recovered_deleted_profiles > 0


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    path: str
    name: str
    size: int
    modified_at: str
    reason: str = ""


def backup_database_snapshot(reason: str = "startup", keep: int = 30) -> Path | None:
    ensure_app_directories()
    if not DATABASE_PATH.is_file() or DATABASE_PATH.stat().st_size <= 0:
        return None
    DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = DB_BACKUP_DIR / f"app-{reason}-{timestamp}.db"
    try:
        source = sqlite3.connect(DATABASE_PATH)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    except sqlite3.Error:
        target = DB_BACKUP_DIR / f"app-{reason}-{timestamp}.raw.db"
        shutil.copy2(DATABASE_PATH, target)
    prune_database_snapshots(keep=keep)
    return target


def prune_database_snapshots(keep: int = 30) -> None:
    if not DB_BACKUP_DIR.exists():
        return
    backups = sorted(
        {item for item in DB_BACKUP_DIR.glob("app-*.db")} | {item for item in DB_BACKUP_DIR.glob("app-*.raw.db")},
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in backups[max(1, keep):]:
        old.unlink(missing_ok=True)


def list_database_snapshots(limit: int = 30) -> list[DatabaseSnapshot]:
    if not DB_BACKUP_DIR.exists():
        return []
    snapshots = sorted(
        {item for item in DB_BACKUP_DIR.glob("app-*.db")} | {item for item in DB_BACKUP_DIR.glob("app-*.raw.db")},
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    records: list[DatabaseSnapshot] = []
    for item in snapshots[: max(1, limit)]:
        stat = item.stat()
        parts = item.stem.split("-")
        reason = parts[1] if len(parts) >= 3 else ""
        records.append(
            DatabaseSnapshot(
                path=str(item),
                name=item.name,
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                reason=reason,
            )
        )
    return records


def orphaned_profile_directories(connection: sqlite3.Connection) -> list[Path]:
    ensure_app_directories()
    if not PROFILE_STORAGE_DIR.exists():
        return []
    rows = connection.execute("SELECT id FROM profiles").fetchall()
    existing_ids = {str(row["id"]) for row in rows}
    orphans: list[Path] = []
    for directory in sorted(PROFILE_STORAGE_DIR.iterdir(), key=lambda item: item.name.casefold()):
        if directory.is_dir() and directory.name not in existing_ids:
            candidate = profile_from_sidecar_or_directory(
                directory,
                existing_names=set(),
                used_seeds=set(),
                recovered_index=len(orphans) + 1,
            )
            if candidate is not None:
                orphans.append(directory)
    return orphans


def recover_orphaned_profiles(connection: sqlite3.Connection) -> StartupRecoveryReport:
    ensure_app_directories()
    report = StartupRecoveryReport(orphan_directories=[])
    if not PROFILE_STORAGE_DIR.exists():
        return report

    existing_rows = connection.execute("SELECT id, name, fingerprint_seed FROM profiles").fetchall()
    existing_ids = {str(row["id"]) for row in existing_rows}
    existing_names = {str(row["name"]).casefold() for row in existing_rows}
    used_seeds = {
        int(row["fingerprint_seed"])
        for row in existing_rows
        if row["fingerprint_seed"] is not None
    }

    recovered: list[Profile] = []
    for directory in sorted(PROFILE_STORAGE_DIR.iterdir(), key=lambda item: item.name.casefold()):
        if not directory.is_dir() or directory.name in existing_ids:
            continue
        candidate = profile_from_sidecar_or_directory(
            directory,
            existing_names=existing_names,
            used_seeds=used_seeds,
            recovered_index=len(recovered) + 1,
        )
        if candidate is None:
            continue
        recovered.append(candidate)
        report.orphan_directories.append(directory.name)

    if not recovered:
        return report

    connection.executemany(
        """
        INSERT OR IGNORE INTO profiles (
            id, name, proxy, timezone, locale, screen_width, screen_height,
            fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
            extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
            last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [profile.to_db_tuple() for profile in recovered],
    )
    for profile in recovered:
        try:
            write_profile_sidecar(profile)
        except OSError:
            pass
        if profile.deleted_at:
            report.recovered_deleted_profiles += 1
        else:
            report.recovered_profiles += 1
    return report
