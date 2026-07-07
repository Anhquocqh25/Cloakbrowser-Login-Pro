from __future__ import annotations

from database.db import get_connection
from models.profile import Profile
from services.profile_sidecar import write_profile_sidecar


class ProfileRepository:
    def _profile_from_row(self, row) -> Profile | None:
        return Profile.from_row(row) if row else None

    def _select_profile(self, connection, profile_id: str) -> Profile | None:
        row = connection.execute(
            """
            SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                   fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                   extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                   last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
            FROM profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
        return self._profile_from_row(row)

    def _sync_sidecar(self, profile: Profile | None) -> None:
        if profile is not None:
            try:
                write_profile_sidecar(profile)
            except OSError:
                pass

    def list_profiles(self) -> list[Profile]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                       fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                       extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                       last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                FROM profiles
                WHERE COALESCE(deleted_at, '') = ''
                ORDER BY created_at DESC, name COLLATE NOCASE ASC
                """
            ).fetchall()
        return [Profile.from_row(row) for row in rows]

    def get_profile(self, profile_id: str) -> Profile | None:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                       fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                       extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                       last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                FROM profiles
                WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
        return self._profile_from_row(row)

    def create_profile(self, profile: Profile) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO profiles (
                    id, name, proxy, timezone, locale, screen_width, screen_height,
                    fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                    extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                    last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                profile.to_db_tuple(),
            )
            connection.commit()
        self._sync_sidecar(profile)

    def create_profiles(self, profiles: list[Profile]) -> None:
        if not profiles:
            return
        with get_connection() as connection:
            connection.executemany(
                """
                INSERT INTO profiles (
                    id, name, proxy, timezone, locale, screen_width, screen_height,
                    fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                    extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                    last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [profile.to_db_tuple() for profile in profiles],
            )
            connection.commit()
        for profile in profiles:
            self._sync_sidecar(profile)

    def update_profile(self, profile: Profile) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE profiles
                SET name = ?,
                    proxy = ?,
                    timezone = ?,
                    locale = ?,
                    screen_width = ?,
                    screen_height = ?,
                    fingerprint_seed = ?,
                    auto_geoip = ?,
                    platform = ?,
                    browser_engine = ?,
                    notes = ?,
                    user_agent = ?,
                    startup_url = ?,
                    extension_ids = ?,
                    bookmark_ids = ?,
                    status = ?,
                    deleted_at = ?,
                    group_name = ?,
                    tags = ?,
                    pinned = ?,
                    last_used_at = ?,
                    health_status = ?,
                    health_checked_at = ?,
                    seed_locked = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    profile.name,
                    profile.proxy,
                    profile.timezone,
                    profile.locale,
                    profile.screen_width,
                    profile.screen_height,
                    profile.fingerprint_seed,
                    int(profile.auto_geoip),
                    profile.platform,
                    profile.browser_engine,
                    profile.notes,
                    profile.user_agent,
                    profile.startup_url,
                    __import__("json").dumps(profile.extension_ids) if profile.extension_ids is not None else None,
                    __import__("json").dumps(profile.bookmark_ids) if profile.bookmark_ids is not None else None,
                    profile.status,
                    profile.deleted_at,
                    profile.group_name,
                    profile.tags,
                    int(profile.pinned),
                    profile.last_used_at,
                    profile.health_status,
                    profile.health_checked_at,
                    int(profile.seed_locked),
                    profile.updated_at,
                    profile.id,
                ),
            )
            connection.commit()
        self._sync_sidecar(profile)

    def list_deleted_profiles(self) -> list[Profile]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                       fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                       extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                       last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                FROM profiles
                WHERE COALESCE(deleted_at, '') != ''
                ORDER BY deleted_at DESC, name COLLATE NOCASE ASC
                """
            ).fetchall()
        return [Profile.from_row(row) for row in rows]

    def move_to_trash(self, profile_id: str, deleted_at: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE profiles SET deleted_at = ?, status = 'stopped', updated_at = ? WHERE id = ?",
                (deleted_at, deleted_at, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def restore_profile(self, profile_id: str, updated_at: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE profiles SET deleted_at = '', status = 'stopped', updated_at = ? WHERE id = ?",
                (updated_at, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def update_status(self, profile_id: str, status: str, updated_at: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE profiles
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, updated_at, profile_id),
            )
            connection.commit()

    def update_metadata(self, profile_id: str, field: str, value: object, updated_at: str) -> None:
        allowed = {"name", "notes", "tags", "group_name", "pinned"}
        if field not in allowed:
            raise ValueError("Unsupported profile field.")
        with get_connection() as connection:
            connection.execute(
                f"UPDATE profiles SET {field} = ?, updated_at = ? WHERE id = ?",
                (int(value) if field == "pinned" else value, updated_at, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def update_health(self, profile_id: str, status: str, checked_at: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE profiles SET health_status = ?, health_checked_at = ? WHERE id = ?",
                (status, checked_at, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def mark_used(self, profile_id: str, timestamp: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE profiles SET last_used_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def set_seed_locked(self, profile_id: str, locked: bool, updated_at: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE profiles SET seed_locked = ?, updated_at = ? WHERE id = ?",
                (int(locked), updated_at, profile_id),
            )
            profile = self._select_profile(connection, profile_id)
            connection.commit()
        self._sync_sidecar(profile)

    def replace_proxy_url(self, old_url: str, new_url: str, updated_at: str) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                "UPDATE profiles SET proxy = ?, updated_at = ? WHERE proxy = ?",
                (new_url, updated_at, old_url),
            )
            profiles = [
                self._profile_from_row(row)
                for row in connection.execute(
                    """
                    SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                           fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                           extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                           last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                    FROM profiles
                    WHERE proxy = ?
                    """,
                    (new_url,),
                ).fetchall()
            ]
            connection.commit()
            for profile in profiles:
                self._sync_sidecar(profile)
            return cursor.rowcount

    def clear_proxy_url(self, url: str, updated_at: str) -> int:
        with get_connection() as connection:
            cursor = connection.execute(
                "UPDATE profiles SET proxy = NULL, updated_at = ? WHERE proxy = ?",
                (updated_at, url),
            )
            profiles = [
                self._profile_from_row(row)
                for row in connection.execute(
                    """
                    SELECT id, name, proxy, timezone, locale, screen_width, screen_height,
                           fingerprint_seed, auto_geoip, platform, browser_engine, notes, user_agent, startup_url,
                           extension_ids, bookmark_ids, status, deleted_at, group_name, tags, pinned,
                           last_used_at, health_status, health_checked_at, seed_locked, created_at, updated_at
                    FROM profiles
                    WHERE updated_at = ? AND proxy IS NULL
                    """,
                    (updated_at,),
                ).fetchall()
            ]
            connection.commit()
            for profile in profiles:
                self._sync_sidecar(profile)
            return cursor.rowcount

    def delete_profile(self, profile_id: str) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            connection.commit()
