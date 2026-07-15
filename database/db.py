from __future__ import annotations

import sqlite3

from config import DATABASE_PATH
from services.data_guard import StartupRecoveryReport, backup_database_snapshot, recover_orphaned_profiles
from utils.paths import ensure_app_directories
from utils.secret_store import decrypt_proxy_field, encrypt_proxy_field, is_encrypted


CREATE_PROFILES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    proxy TEXT,
    timezone TEXT DEFAULT 'Asia/Bangkok',
    locale TEXT DEFAULT 'en-US',
    screen_width INTEGER DEFAULT 1200,
    screen_height INTEGER DEFAULT 800,
    fingerprint_seed INTEGER,
    auto_geoip INTEGER DEFAULT 1,
    platform TEXT DEFAULT 'windows',
    browser_engine TEXT DEFAULT 'cloak',
    notes TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    startup_url TEXT DEFAULT '',
    extension_ids TEXT,
    bookmark_ids TEXT,
    status TEXT DEFAULT 'stopped',
    deleted_at TEXT DEFAULT '',
    group_name TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    pinned INTEGER DEFAULT 0,
    last_used_at TEXT DEFAULT '',
    health_status TEXT DEFAULT 'unknown',
    health_checked_at TEXT DEFAULT '',
    seed_locked INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
"""

CREATE_PROXIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS proxies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    location TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT,
    status TEXT DEFAULT 'unknown',
    latency_ms INTEGER DEFAULT 0,
    exit_ip TEXT DEFAULT '',
    last_checked_at TEXT DEFAULT '',
    check_error TEXT DEFAULT ''
    ,country_code TEXT DEFAULT ''
    ,geo_timezone TEXT DEFAULT ''
    ,enabled INTEGER DEFAULT 1
    ,success_count INTEGER DEFAULT 0
    ,failure_count INTEGER DEFAULT 0
    ,consecutive_failures INTEGER DEFAULT 0
    ,quality_score INTEGER DEFAULT 0
    ,cooldown_until TEXT DEFAULT ''
)
"""

CREATE_EXTENSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS extensions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    enabled INTEGER DEFAULT 1,
    created_at TEXT
)
"""

CREATE_BOOKMARKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    folder TEXT DEFAULT 'Fingerprint Tests',
    created_at TEXT
)
"""

CREATE_ACTIVITY_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    profile_id TEXT DEFAULT '',
    profile_name TEXT DEFAULT '',
    severity TEXT DEFAULT 'info',
    details TEXT DEFAULT ''
)
"""

CREATE_HEALTH_CHECKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT DEFAULT '',
    details TEXT DEFAULT ''
)
"""

CREATE_FINGERPRINT_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fingerprint_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT DEFAULT 'baseline',
    cloak_version TEXT DEFAULT '',
    fingerprint_hash TEXT NOT NULL,
    status TEXT DEFAULT 'pass',
    data_json TEXT NOT NULL,
    differences_json TEXT DEFAULT '{}'
)
"""

DEFAULT_BOOKMARKS = [
    ("default-iphey", "IPhey", "https://iphey.com/", "Fingerprint Tests"),
    ("default-browserscan", "BrowserScan", "https://browserscan.org/", "Fingerprint Tests"),
    ("default-browserleaks", "BrowserLeaks", "https://browserleaks.com/", "Fingerprint Tests"),
    ("default-creepjs", "CreepJS", "https://abrahamjuliot.github.io/creepjs/", "Fingerprint Tests"),
    ("default-fingerprintjs", "FingerprintJS Demo", "https://fingerprint.com/demo/", "Fingerprint Tests"),
]


def get_connection() -> sqlite3.Connection:
    ensure_app_directories()
    connection = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    connection.row_factory = sqlite3.Row
    # Reliability under concurrent UI + worker threads (still one connection per call).
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> StartupRecoveryReport:
    backup_path = backup_database_snapshot("startup")
    with get_connection() as connection:
        connection.execute(CREATE_PROFILES_TABLE_SQL)
        connection.execute(CREATE_PROXIES_TABLE_SQL)
        connection.execute(CREATE_EXTENSIONS_TABLE_SQL)
        connection.execute(CREATE_BOOKMARKS_TABLE_SQL)
        connection.execute(CREATE_ACTIVITY_LOGS_TABLE_SQL)
        connection.execute(CREATE_HEALTH_CHECKS_TABLE_SQL)
        connection.execute(CREATE_FINGERPRINT_SNAPSHOTS_TABLE_SQL)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(profiles)").fetchall()}
        if "auto_geoip" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN auto_geoip INTEGER DEFAULT 1")
        if "platform" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN platform TEXT DEFAULT 'windows'")
        if "browser_engine" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN browser_engine TEXT DEFAULT 'cloak'")
        if "notes" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN notes TEXT DEFAULT ''")
        if "user_agent" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN user_agent TEXT DEFAULT ''")
        if "startup_url" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN startup_url TEXT DEFAULT ''")
        if "extension_ids" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN extension_ids TEXT")
        if "bookmark_ids" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN bookmark_ids TEXT")
        if "deleted_at" not in columns:
            connection.execute("ALTER TABLE profiles ADD COLUMN deleted_at TEXT DEFAULT ''")
        for name, sql_type, default in (
            ("group_name", "TEXT", "''"), ("tags", "TEXT", "''"),
            ("pinned", "INTEGER", "0"), ("last_used_at", "TEXT", "''"),
            ("health_status", "TEXT", "'unknown'"),
            ("health_checked_at", "TEXT", "''"),
            ("seed_locked", "INTEGER", "0"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE profiles ADD COLUMN {name} {sql_type} DEFAULT {default}")
        proxy_columns = {row[1] for row in connection.execute("PRAGMA table_info(proxies)").fetchall()}
        if "status" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN status TEXT DEFAULT 'unknown'")
        if "latency_ms" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN latency_ms INTEGER DEFAULT 0")
        if "exit_ip" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN exit_ip TEXT DEFAULT ''")
        if "last_checked_at" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN last_checked_at TEXT DEFAULT ''")
        if "check_error" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN check_error TEXT DEFAULT ''")
        if "country_code" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN country_code TEXT DEFAULT ''")
        if "geo_timezone" not in proxy_columns:
            connection.execute("ALTER TABLE proxies ADD COLUMN geo_timezone TEXT DEFAULT ''")
        for name, sql_type, default in (
            ("enabled", "INTEGER", "1"),
            ("success_count", "INTEGER", "0"),
            ("failure_count", "INTEGER", "0"),
            ("consecutive_failures", "INTEGER", "0"),
            ("quality_score", "INTEGER", "0"),
            ("cooldown_until", "TEXT", "''"),
        ):
            if name not in proxy_columns:
                connection.execute(f"ALTER TABLE proxies ADD COLUMN {name} {sql_type} DEFAULT {default}")
        for bookmark_id, title, url, folder in DEFAULT_BOOKMARKS:
            connection.execute(
                "INSERT OR IGNORE INTO bookmarks (id, title, url, folder, created_at) VALUES (?, ?, ?, ?, '')",
                (bookmark_id, title, url, folder),
            )
        # Running browser objects cannot survive an application restart.
        connection.execute("UPDATE profiles SET status = 'stopped' WHERE status != 'stopped'")
        _migrate_proxy_secrets(connection)
        report = recover_orphaned_profiles(connection)
        if backup_path:
            report.database_backup = str(backup_path)
        connection.commit()
        return report


def _migrate_proxy_secrets(connection: sqlite3.Connection) -> None:
    """Encrypt legacy plaintext proxy URLs at rest (Windows DPAPI). Non-fatal on failure."""
    try:
        proxy_rows = connection.execute("SELECT id, url FROM proxies").fetchall()
        for row in proxy_rows:
            url = row["url"] or ""
            if not url or is_encrypted(url):
                continue
            try:
                stored = encrypt_proxy_field(url)
            except OSError:
                continue
            if stored and stored != url:
                connection.execute("UPDATE proxies SET url = ? WHERE id = ?", (stored, row["id"]))

        profile_rows = connection.execute(
            "SELECT id, proxy FROM profiles WHERE proxy IS NOT NULL AND TRIM(proxy) != ''"
        ).fetchall()
        for row in profile_rows:
            proxy = row["proxy"] or ""
            if not proxy or is_encrypted(proxy):
                continue
            try:
                stored = encrypt_proxy_field(proxy)
            except OSError:
                continue
            if stored and stored != proxy:
                connection.execute("UPDATE profiles SET proxy = ? WHERE id = ?", (stored, row["id"]))
    except sqlite3.Error:
        # Keep startup resilient; app can still run with mixed legacy values.
        return
