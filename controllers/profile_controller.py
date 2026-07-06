from __future__ import annotations

import random
import shutil
import threading
import uuid
import json
import csv
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from browser.launcher import BrowserLaunchError, builtin_extension_dir, close_browser, launch_browser
from config import BACKUP_STORAGE_DIR, DEFAULT_LOCALE, DEFAULT_SCREEN_HEIGHT, DEFAULT_SCREEN_WIDTH, DEFAULT_TIMEZONE, EXTENSION_STORAGE_DIR
from database.profile_repository import ProfileRepository
from database.bookmark_repository import BookmarkRepository
from database.extension_repository import ExtensionRepository
from database.proxy_repository import ProxyRepository
from database.maintenance_repository import MaintenanceRepository
from models.bookmark import BookmarkRecord
from models.extension import ExtensionRecord
from models.profile import Profile
from models.proxy import ProxyRecord
from storage.config_store import ConfigStore
from utils.bookmark_config import write_bookmark_config
from utils.extension_downloader import download_and_install_extension
from utils.paths import profile_user_data_dir
from utils.proxy_parser import normalize_proxy
from utils.proxy_checker import ProxyCheckResult, check_proxy as perform_proxy_check
from utils.startup_url import normalize_startup_url
from services.backup_service import (
    create_full_backup, export_profile, finish_profile_import, prune_backups,
    read_imported_profile, restore_full_backup,
)
from services.fingerprint_engine import (
    check_consistency, compare_snapshots, detect_duplicates, fingerprint_hash,
    regression_status, snapshot_data,
)
from services.compatibility_guard import blocker_message, check_profile_compatibility

try:
    from cloakbrowser import __version__ as cloak_wrapper_version
    from cloakbrowser import binary_info as cloak_binary_info
    from cloakbrowser import check_for_update as cloak_check_for_update
except ImportError:
    cloak_wrapper_version = "unavailable"
    cloak_binary_info = None
    cloak_check_for_update = None


class BrowserSessionWorker(QObject):
    """Own one directly launched browser process for the lifetime of its QThread."""

    opened = Signal(str)
    closed = Signal(str)
    failed = Signal(str, str)

    def __init__(self, profile: Profile, extension_paths: list[str] | None = None) -> None:
        super().__init__()
        self.profile = profile
        self.extension_paths = extension_paths or []
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        context = None
        try:
            context = launch_browser(self.profile, self.extension_paths)
            self.opened.emit(self.profile.id)
            while not self._stop_requested.is_set() and context.is_alive():
                self._stop_requested.wait(0.25)
            close_browser(context)
            self.closed.emit(self.profile.id)
        except Exception as error:
            if context is not None:
                try:
                    close_browser(context)
                except Exception:
                    pass
            self.failed.emit(self.profile.id, str(error))


class ProxyCheckWorker(QObject):
    finished = Signal(str, str, object)

    def __init__(self, kind: str, target_id: str, proxy_url: str) -> None:
        super().__init__()
        self.kind = kind
        self.target_id = target_id
        self.proxy_url = proxy_url

    def run(self) -> None:
        result = perform_proxy_check(self.proxy_url)
        self.finished.emit(self.kind, self.target_id, result)


class ProfileHealthWorker(QObject):
    finished = Signal(str, object)

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self.profile = profile

    def run(self) -> None:
        profile = self.profile
        details: dict[str, dict[str, object]] = {}
        if profile.proxy:
            result = perform_proxy_check(profile.proxy)
            details["proxy"] = {
                "status": "pass" if result.alive else "fail",
                "message": f"{result.exit_ip} · {result.latency_ms} ms" if result.alive else result.error,
            }
            details["ip"] = {"status": "pass" if result.alive else "fail", "message": result.exit_ip or "Unavailable"}
            details["webrtc"] = {"status": "pass", "message": "Proxy-only WebRTC policy enabled"}
            details["dns"] = {"status": "pass", "message": "DNS traffic routed through proxy bridge"}
        else:
            details["proxy"] = {"status": "warning", "message": "Direct connection"}
            details["ip"] = {"status": "warning", "message": "Machine public IP will be used"}
            details["webrtc"] = {"status": "warning", "message": "No proxy isolation required"}
            details["dns"] = {"status": "warning", "message": "System DNS will be used"}
        details["timezone"] = {
            "status": "pass" if profile.auto_geoip and profile.proxy else "warning",
            "message": "Matched to proxy at launch" if profile.auto_geoip and profile.proxy else f"Manual: {profile.timezone}",
        }
        if profile.browser_engine == "cloak":
            fingerprint_ok = bool(profile.fingerprint_seed)
            details["fingerprint"] = {
                "status": "pass" if fingerprint_ok else "fail",
                "message": f"Cloak seed {profile.fingerprint_seed}" if fingerprint_ok else "Fingerprint seed missing",
            }
        else:
            details["fingerprint"] = {"status": "warning", "message": "Native Chrome uses its natural fingerprint"}
        statuses = [item["status"] for item in details.values()]
        status = "fail" if "fail" in statuses else ("warning" if "warning" in statuses else "pass")
        passed = sum(1 for item in statuses if item == "pass")
        payload = {
            "status": status,
            "summary": f"{passed}/{len(statuses)} checks passed",
            "details": details,
            "timestamp": Profile.now_timestamp(),
        }
        self.finished.emit(profile.id, payload)


class MaintenanceWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, key: str, operation) -> None:
        super().__init__()
        self.key = key
        self.operation = operation

    def run(self) -> None:
        try:
            self.finished.emit(self.key, self.operation())
        except Exception as error:
            self.failed.emit(self.key, str(error))


class ProfileController(QObject):
    profiles_changed = Signal(list)
    profile_opened = Signal(str)
    profile_closed = Signal(str)
    operation_failed = Signal(str)
    info_message = Signal(str)
    proxies_changed = Signal(list)
    extensions_changed = Signal(list)
    bookmarks_changed = Signal(list)
    trash_changed = Signal(list)
    activity_changed = Signal(list)
    health_changed = Signal(list)
    backup_completed = Signal(str)
    restore_completed = Signal()
    fingerprint_changed = Signal(dict)
    cloak_versions_changed = Signal(dict)
    task_started = Signal(str, str, str)
    task_progress = Signal(str, int, str)
    task_finished = Signal(str, bool, str)

    def __init__(
        self,
        repository: ProfileRepository,
        proxy_repository: ProxyRepository | None = None,
        extension_repository: ExtensionRepository | None = None,
        bookmark_repository: BookmarkRepository | None = None,
        config_store: ConfigStore | None = None,
        maintenance_repository: MaintenanceRepository | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.proxy_repository = proxy_repository or ProxyRepository()
        self.extension_repository = extension_repository or ExtensionRepository()
        self.bookmark_repository = bookmark_repository or BookmarkRepository()
        self.config_store = config_store or ConfigStore()
        self.maintenance_repository = maintenance_repository or MaintenanceRepository()
        self.running_profiles: dict[str, BrowserSessionWorker] = {}
        self.worker_threads: dict[str, QThread] = {}
        self.workers: dict[str, BrowserSessionWorker] = {}
        self.proxy_check_threads: dict[str, QThread] = {}
        self.proxy_check_workers: dict[str, ProxyCheckWorker] = {}
        self.cancelled_proxy_checks: set[str] = set()
        self.pending_delete_profile_ids: set[str] = set()
        self.health_threads: dict[str, QThread] = {}
        self.health_workers: dict[str, ProfileHealthWorker] = {}
        self.maintenance_threads: dict[str, QThread] = {}
        self.maintenance_workers: dict[str, MaintenanceWorker] = {}
        self.proxy_batch_ids: set[str] = set()
        self.proxy_batch_total = 0
        self.trash_cleanup_timer = QTimer(self)
        self.trash_cleanup_timer.setInterval(60 * 60 * 1000)
        self.trash_cleanup_timer.timeout.connect(self.purge_expired_profiles)
        self.trash_cleanup_timer.start()
        self.process_reconcile_timer = QTimer(self)
        self.process_reconcile_timer.setInterval(2500)
        self.process_reconcile_timer.timeout.connect(self.reconcile_profile_statuses)
        self.process_reconcile_timer.start()
        self.backup_timer = QTimer(self)
        self.backup_timer.setInterval(60 * 60 * 1000)
        self.backup_timer.timeout.connect(self.run_automatic_backup_if_due)
        self.backup_timer.start()
        self.proxy_pool_timer = QTimer(self)
        self.proxy_pool_timer.setInterval(60 * 1000)
        self.proxy_pool_timer.timeout.connect(self.run_proxy_pool_cycle)
        self.proxy_pool_timer.start()
        self.purge_expired_profiles()
        QTimer.singleShot(5000, self.run_automatic_backup_if_due)
        QTimer.singleShot(15000, self.run_proxy_pool_cycle)

    def _log(self, action: str, profile: Profile | None = None, severity: str = "info", details: str = "") -> None:
        self.maintenance_repository.log(
            action,
            profile_id=profile.id if profile else "",
            profile_name=profile.name if profile else "",
            severity=severity,
            details=details,
        )
        self.load_activity()

    def load_activity(self) -> list[dict]:
        records = self.maintenance_repository.list_activity()
        self.activity_changed.emit(records)
        return records

    def load_health(self) -> list[dict]:
        records = self.maintenance_repository.list_health()
        self.health_changed.emit(records)
        return records

    def cloak_version_info(self) -> dict:
        pinned = self.config_store.cloak_browser_version()
        if cloak_binary_info is None:
            info = {"version": "unavailable", "installed": False, "binary_path": "", "tier": "", "platform": ""}
        else:
            try:
                info = dict(cloak_binary_info(pinned or None))
            except Exception as error:
                info = {"version": pinned or "unknown", "installed": False, "binary_path": "", "tier": "", "platform": "", "error": str(error)}
        cache_dir = Path(str(info.get("cache_dir") or Path.home() / ".cloakbrowser"))
        cache_root = cache_dir.parent if cache_dir.name.startswith("chromium-") else cache_dir
        cached: list[str] = []
        if cache_root.exists():
            for folder in cache_root.glob("chromium-*"):
                if folder.is_dir() and (folder / "chrome.exe").exists():
                    cached.append(folder.name.removeprefix("chromium-"))
        info.update({
            "wrapper_version": cloak_wrapper_version,
            "pinned_version": pinned,
            "cached_versions": sorted(set(cached), reverse=True),
        })
        return info

    def load_fingerprint_lab(self) -> dict:
        version = self.cloak_version_info()
        profiles = self.repository.list_profiles()
        duplicates = detect_duplicates(profiles, version)
        rows: list[dict] = []
        for profile in profiles:
            report = check_consistency(profile, version)
            baseline = self.maintenance_repository.latest_baseline(profile.id)
            current = snapshot_data(replace(profile, cloak_version=self.config_store.cloak_browser_version()), version)
            differences = compare_snapshots(baseline.get("data", {}), current) if baseline else {}
            rows.append({
                "profile_id": profile.id,
                "name": profile.name,
                "seed": profile.fingerprint_seed,
                "seed_locked": profile.seed_locked,
                "consistency_status": report.status,
                "score": report.score,
                "summary": report.summary,
                "checks": report.checks,
                "baseline_at": baseline.get("created_at", "") if baseline else "",
                "differences": differences,
                "duplicate_count": len(duplicates.get(profile.id, [])),
                "duplicates": duplicates.get(profile.id, []),
            })
        payload = {
            "version": version,
            "profiles": rows,
            "snapshots": self.maintenance_repository.list_fingerprint_snapshots(limit=500),
        }
        self.cloak_versions_changed.emit(version)
        self.fingerprint_changed.emit(payload)
        return payload

    def set_cloak_version(self, version: str) -> None:
        clean = str(version or "").strip()
        info = self.cloak_version_info()
        if clean and clean not in info.get("cached_versions", []):
            raise ValueError("The selected CloakBrowser version is not installed.")
        if self.worker_threads:
            raise BrowserLaunchError("Close all profiles before changing the CloakBrowser version.")
        self.config_store.set_cloak_browser_version(clean)
        self._log("cloak.version_selected", details=clean or "automatic")
        self.load_fingerprint_lab()

    def check_cloak_update(self) -> None:
        if cloak_check_for_update is None:
            raise RuntimeError("CloakBrowser update API is unavailable.")
        self._start_maintenance("cloak_update", cloak_check_for_update)
        self.info_message.emit("Checking for CloakBrowser updates...")

    def set_seed_locked(self, profile_id: str, locked: bool) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile or profile.deleted_at:
            raise ValueError("Profile does not exist.")
        if profile.status != "stopped":
            raise BrowserLaunchError("Stop the profile before changing Seed Lock.")
        self.repository.set_seed_locked(profile_id, locked, Profile.now_timestamp())
        self._log("fingerprint.seed_locked" if locked else "fingerprint.seed_unlocked", profile, "warning" if not locked else "info")
        self.load_profiles()
        self.load_fingerprint_lab()

    def create_fingerprint_snapshot(self, profile_id: str) -> dict:
        profile = self.repository.get_profile(profile_id)
        if not profile or profile.deleted_at:
            raise ValueError("Profile does not exist.")
        if not profile.seed_locked and profile.browser_engine == "cloak":
            self.repository.set_seed_locked(profile.id, True, Profile.now_timestamp())
            profile.seed_locked = True
        version = self.cloak_version_info()
        effective = replace(profile, cloak_version=self.config_store.cloak_browser_version())
        data = snapshot_data(effective, version)
        previous = self.maintenance_repository.latest_baseline(profile_id)
        differences = compare_snapshots(previous.get("data", {}), data) if previous else {}
        status = regression_status(differences) if previous else "pass"
        snapshot_id = self.maintenance_repository.save_fingerprint_snapshot(
            profile.id, profile.name, "baseline", str(version.get("version") or ""),
            fingerprint_hash(data), status, data, differences, Profile.now_timestamp(),
        )
        self._log("fingerprint.snapshot_created", profile, details=f"Snapshot {snapshot_id}")
        self.load_profiles(); self.load_fingerprint_lab()
        return {"id": snapshot_id, "status": status, "differences": differences}

    def run_regression_test(self, profile_ids: list[str] | None = None) -> list[dict]:
        profiles = self.repository.list_profiles()
        if profile_ids is not None:
            selected = set(profile_ids)
            profiles = [profile for profile in profiles if profile.id in selected]
        version = self.cloak_version_info()
        results: list[dict] = []
        rank = {"pass": 0, "warning": 1, "fail": 2}
        for profile in profiles:
            effective = replace(profile, cloak_version=self.config_store.cloak_browser_version())
            current = snapshot_data(effective, version)
            baseline = self.maintenance_repository.latest_baseline(profile.id)
            consistency = check_consistency(profile, version)
            if baseline:
                differences = compare_snapshots(baseline.get("data", {}), current)
                status = regression_status(differences)
            else:
                differences = {"baseline": {"before": None, "after": "Missing"}}
                status = "warning"
            if rank[consistency.status] > rank[status]:
                status = consistency.status
            snapshot_id = self.maintenance_repository.save_fingerprint_snapshot(
                profile.id, profile.name, "regression", str(version.get("version") or ""),
                fingerprint_hash(current), status, current, differences, Profile.now_timestamp(),
            )
            results.append({"profile_id": profile.id, "name": profile.name, "status": status, "differences": differences, "snapshot_id": snapshot_id})
        failures = sum(1 for item in results if item["status"] == "fail")
        self._log("fingerprint.regression_completed", severity="warning" if failures else "info", details=f"{len(results)} profile(s), {failures} failed")
        self.load_fingerprint_lab()
        return results

    def load_profiles(self) -> list[Profile]:
        profiles = self.repository.list_profiles()
        self.profiles_changed.emit(profiles)
        return profiles

    def load_trash(self) -> list[Profile]:
        profiles = self.repository.list_deleted_profiles()
        self.trash_changed.emit(profiles)
        return profiles

    def get_profile(self, profile_id: str) -> Profile | None:
        return self.repository.get_profile(profile_id)

    def load_proxies(self) -> list[ProxyRecord]:
        records = self.proxy_repository.list_all()
        self.proxies_changed.emit(records)
        return records

    def save_proxy(
        self, name: str, url: str, location: str = "", notes: str = "", proxy_id: str | None = None
    ) -> ProxyRecord:
        clean_url = normalize_proxy(url)
        if not clean_url:
            raise ValueError("Proxy cannot be empty.")
        duplicate = next(
            (
                item for item in self.proxy_repository.list_all()
                if item.url == clean_url and item.id != proxy_id
            ),
            None,
        )
        if duplicate:
            raise ValueError(f"This proxy is already saved as {duplicate.name}.")
        existing = self.proxy_repository.get(proxy_id) if proxy_id else None
        linked_profiles = [
            profile for profile in self.repository.list_profiles()
            if existing and profile.proxy == existing.url
        ]
        if existing and existing.url != clean_url and any(
            profile.status != "stopped" for profile in linked_profiles
        ):
            raise BrowserLaunchError("Stop profiles using this proxy before changing its address.")
        keep_result = existing is not None and existing.url == clean_url
        record = ProxyRecord(
            id=proxy_id or str(uuid.uuid4()), name=name.strip(), url=clean_url,
            location=location.strip(), notes=notes.strip(), created_at=Profile.now_timestamp(),
            status=existing.status if keep_result else "unknown",
            latency_ms=existing.latency_ms if keep_result else 0,
            exit_ip=existing.exit_ip if keep_result else "",
            last_checked_at=existing.last_checked_at if keep_result else "",
            check_error=existing.check_error if keep_result else "",
            country_code=existing.country_code if keep_result else "",
            timezone=existing.timezone if keep_result else "",
            enabled=existing.enabled if keep_result else True,
            success_count=existing.success_count if keep_result else 0,
            failure_count=existing.failure_count if keep_result else 0,
            consecutive_failures=existing.consecutive_failures if keep_result else 0,
            quality_score=existing.quality_score if keep_result else 0,
            cooldown_until=existing.cooldown_until if keep_result else "",
        )
        self.proxy_repository.save(record)
        if existing and existing.url != clean_url:
            updated = self.repository.replace_proxy_url(
                existing.url, clean_url, Profile.now_timestamp()
            )
            if updated:
                self.load_profiles()
        self.load_proxies()
        self._log("proxy.updated" if existing else "proxy.created", details=f"{record.name} · {record.url}")
        return record

    def delete_proxy(self, proxy_id: str) -> None:
        record = self.proxy_repository.get(proxy_id)
        if not record:
            return
        linked_profiles = [
            profile for profile in self.repository.list_profiles()
            if profile.proxy == record.url
        ]
        if any(profile.status != "stopped" for profile in linked_profiles):
            raise BrowserLaunchError("Stop profiles using this proxy before deleting it.")
        self.proxy_repository.delete(proxy_id)
        cleared = self.repository.clear_proxy_url(record.url, Profile.now_timestamp())
        if cleared:
            self.load_profiles()
        self.load_proxies()
        if cleared:
            self.info_message.emit(f"Removed proxy from {cleared} profile(s)")
        self._log("proxy.deleted", details=record.name)

    def check_proxy(self, proxy_id: str) -> None:
        record = self.proxy_repository.get(proxy_id)
        if not record:
            raise ValueError("Proxy not found.")
        key = f"proxy:{proxy_id}"
        if key in self.proxy_check_threads:
            return
        self.proxy_repository.update_check_result(proxy_id, "checking")
        self.load_proxies()
        self._start_proxy_check("proxy", proxy_id, record.url)

    def check_all_proxies(self) -> None:
        records = self.proxy_repository.list_all()
        if not records:
            self.info_message.emit("No proxies to check")
            return
        self.proxy_batch_ids = {record.id for record in records}
        self.proxy_batch_total = len(records)
        self.task_started.emit("proxy-pool-check", "Checking proxy pool", f"{len(records)} proxy(s)")
        for record in records:
            self.check_proxy(record.id)
        self.info_message.emit(f"Checking {len(records)} proxy(s)...")

    def run_proxy_pool_cycle(self) -> None:
        if not self.config_store.proxy_pool_enabled():
            return
        cutoff = (datetime.utcnow() - timedelta(minutes=self.config_store.proxy_pool_interval_minutes())).isoformat(timespec="seconds")
        due = [
            item for item in self.proxy_repository.due_for_check(cutoff)
            if f"proxy:{item.id}" not in self.proxy_check_threads
        ][:10]
        if not due:
            return
        self.proxy_batch_ids.update(item.id for item in due)
        self.proxy_batch_total = max(self.proxy_batch_total, len(self.proxy_batch_ids))
        self.task_started.emit("proxy-pool-check", "Smart Proxy Pool health check", f"{len(due)} due")
        for record in due:
            self.check_proxy(record.id)

    def best_proxy(self, country_code: str = "") -> ProxyRecord | None:
        return self.proxy_repository.best_available(country_code)

    def set_proxy_enabled(self, proxy_id: str, enabled: bool) -> None:
        self.proxy_repository.set_enabled(proxy_id, enabled)
        self.load_proxies()
        record = self.proxy_repository.get(proxy_id)
        self._log("proxy.enabled" if enabled else "proxy.disabled", details=record.name if record else proxy_id)

    def _update_proxy_batch_task(self, proxy_id: str) -> None:
        if proxy_id not in self.proxy_batch_ids:
            return
        self.proxy_batch_ids.discard(proxy_id)
        completed = max(0, self.proxy_batch_total - len(self.proxy_batch_ids))
        progress = round(completed / max(1, self.proxy_batch_total) * 100)
        if self.proxy_batch_ids:
            self.task_progress.emit("proxy-pool-check", progress, f"{completed}/{self.proxy_batch_total} checked")
        else:
            records = self.proxy_repository.list_all()
            live = sum(item.status == "live" and item.enabled for item in records)
            self.task_finished.emit("proxy-pool-check", True, f"{live}/{len(records)} available")
            self.proxy_batch_total = 0

    def load_extensions(self) -> list[ExtensionRecord]:
        records = self.extension_repository.list_all()
        self.extensions_changed.emit(records)
        return records

    def add_extension(self, folder_path: str) -> ExtensionRecord:
        folder = Path(folder_path).resolve()
        manifest_file = folder / "manifest.json"
        if not manifest_file.exists():
            raise ValueError("Extension folder must contain manifest.json.")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        except Exception as error:
            raise ValueError(f"Could not read manifest.json: {error}") from error
        if int(manifest.get("manifest_version") or 0) not in {2, 3}:
            raise ValueError("Only Manifest V2 and V3 extensions are supported.")
        extension_name = str(manifest.get("name") or folder.name)
        if extension_name.startswith("__MSG_") and extension_name.endswith("__"):
            message_key = extension_name[6:-2]
            locale = str(manifest.get("default_locale") or "en")
            messages_file = folder / "_locales" / locale / "messages.json"
            try:
                messages = json.loads(messages_file.read_text(encoding="utf-8-sig"))
                extension_name = str(messages.get(message_key, {}).get("message") or extension_name)
            except Exception:
                pass
        record = ExtensionRecord(
            id=str(uuid.uuid4()), name=extension_name,
            path=str(folder), enabled=True, created_at=Profile.now_timestamp(),
        )
        self.extension_repository.save(record)
        self.load_extensions()
        self._log("extension.added", details=record.name)
        return record

    def add_extension_from_url(self, source_url: str) -> ExtensionRecord:
        folder = download_and_install_extension(source_url)
        try:
            return self.add_extension(str(folder))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def toggle_extension(self, extension_id: str) -> None:
        record = next((item for item in self.extension_repository.list_all() if item.id == extension_id), None)
        if not record:
            raise ValueError("Extension không tồn tại.")
        record.enabled = not record.enabled
        self.extension_repository.save(record)
        self.load_extensions()
        self._log("extension.toggled", details=f"{record.name}: {'enabled' if record.enabled else 'disabled'}")

    def delete_extension(self, extension_id: str) -> None:
        record = next((item for item in self.extension_repository.list_all() if item.id == extension_id), None)
        self.extension_repository.delete(extension_id)
        if record:
            managed_root = EXTENSION_STORAGE_DIR.resolve()
            extension_path = Path(record.path).resolve()
            if extension_path != managed_root and extension_path.is_relative_to(managed_root):
                shutil.rmtree(extension_path, ignore_errors=True)
        self.load_extensions()
        if record:
            self._log("extension.deleted", details=record.name)

    def load_bookmarks(self) -> list[BookmarkRecord]:
        records = self.bookmark_repository.list_all()
        self.bookmarks_changed.emit(records)
        return records

    def save_bookmark(
        self, title: str, url: str, folder: str = "Fingerprint Tests", bookmark_id: str | None = None
    ) -> BookmarkRecord:
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            raise ValueError("Bookmark phải dùng URL http:// hoặc https://")
        record = BookmarkRecord(
            id=bookmark_id or str(uuid.uuid4()), title=title.strip(), url=clean_url,
            folder=folder.strip() or "Bookmarks", created_at=Profile.now_timestamp(),
        )
        self.bookmark_repository.save(record)
        self._sync_bookmark_extension()
        self.load_bookmarks()
        self._log("bookmark.saved", details=f"{record.title} · {record.url}")
        return record

    def delete_bookmark(self, bookmark_id: str) -> None:
        record = next((item for item in self.bookmark_repository.list_all() if item.id == bookmark_id), None)
        self.bookmark_repository.delete(bookmark_id)
        self._sync_bookmark_extension()
        self.load_bookmarks()
        if record:
            self._log("bookmark.deleted", details=record.title)

    def _sync_bookmark_extension(self) -> None:
        write_bookmark_config(builtin_extension_dir(), self.bookmark_repository.list_all())

    def create_profile(
        self,
        name: str,
        proxy: str | None,
        timezone: str,
        locale: str,
        screen_width: int,
        screen_height: int,
        fingerprint_seed: int | None = None,
        auto_geoip: bool = True,
        platform: str = "windows",
        notes: str = "",
        user_agent: str = "",
        extension_ids: list[str] | None = None,
        bookmark_ids: list[str] | None = None,
        browser_engine: str = "cloak",
        startup_url: str = "",
        group_name: str = "",
        tags: str = "",
        pinned: bool = False,
    ) -> Profile:
        profile_id = str(uuid.uuid4())
        timestamp = Profile.now_timestamp()
        engine = browser_engine if browser_engine in {"cloak", "chrome"} else "cloak"
        if engine == "chrome":
            platform = "windows"
            user_agent = ""
        profile = Profile(
            id=profile_id,
            name=name.strip(),
            proxy=normalize_proxy(proxy) if proxy else None,
            timezone=timezone or DEFAULT_TIMEZONE,
            locale=locale or DEFAULT_LOCALE,
            screen_width=screen_width or DEFAULT_SCREEN_WIDTH,
            screen_height=screen_height or DEFAULT_SCREEN_HEIGHT,
            fingerprint_seed=fingerprint_seed or random.randint(100000, 999999999),
            auto_geoip=auto_geoip,
            platform=platform,
            browser_engine=engine,
            notes=notes.strip(),
            user_agent=user_agent.strip(),
            startup_url=normalize_startup_url(startup_url),
            group_name=group_name.strip(),
            tags=tags.strip(),
            pinned=pinned,
            extension_ids=extension_ids,
            bookmark_ids=bookmark_ids,
            status="stopped",
            created_at=timestamp,
            updated_at=timestamp,
        )
        profile_user_data_dir(profile.id).mkdir(parents=True, exist_ok=True)
        self.repository.create_profile(profile)
        self.load_profiles()
        self._log("profile.created", profile)
        self.info_message.emit(f"Created profile {profile.name}")
        return profile

    def create_profiles_batch(self, payloads: list[dict[str, object]]) -> list[Profile]:
        profiles: list[Profile] = []
        timestamp = Profile.now_timestamp()
        existing_seeds = {
            profile.fingerprint_seed
            for profile in self.repository.list_profiles()
            if profile.fingerprint_seed is not None
        }
        used_seeds = set(existing_seeds)
        screen_sizes = {
            "windows": [(1920, 1080), (1600, 900), (1536, 864), (1440, 900), (1366, 768), (1280, 800)],
            "macos": [(1728, 1117), (1512, 982), (1440, 900), (1280, 800)],
            "linux": [(1920, 1080), (1600, 900), (1440, 900), (1366, 768), (1280, 800)],
        }

        def unique_seed() -> int:
            seed = random.randint(100000, 999999999)
            while seed in used_seeds:
                seed = random.randint(100000, 999999999)
            used_seeds.add(seed)
            return seed

        for payload in payloads:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("Profile name cannot be empty.")
            randomize = bool(payload.get("randomize", True))
            engine = str(payload.get("browser_engine") or "cloak")
            engine = engine if engine in {"cloak", "chrome"} else "cloak"
            requested_platform = "windows" if engine == "chrome" else str(payload.get("platform") or "random")
            if requested_platform == "random":
                platform = random.choice(("windows", "macos", "linux"))
            else:
                platform = requested_platform if requested_platform in screen_sizes else "windows"
            if randomize:
                screen_width, screen_height = random.choice(screen_sizes[platform])
            else:
                screen_width = int(payload.get("screen_width") or DEFAULT_SCREEN_WIDTH)
                screen_height = int(payload.get("screen_height") or DEFAULT_SCREEN_HEIGHT)
            seed = unique_seed()
            platform_label = {"windows": "Windows 11", "macos": "macOS", "linux": "Linux"}[platform]
            shared_notes = str(payload.get("notes") or "").strip()
            config_note = f"{platform_label} · {screen_width}x{screen_height} · {payload.get('locale') or DEFAULT_LOCALE}"
            notes = f"{shared_notes} · {config_note}" if shared_notes else config_note
            profile = Profile(
                id=str(uuid.uuid4()),
                name=name,
                proxy=str(payload.get("proxy") or "") or None,
                timezone=str(payload.get("timezone") or DEFAULT_TIMEZONE),
                locale=str(payload.get("locale") or DEFAULT_LOCALE),
                screen_width=screen_width,
                screen_height=screen_height,
                fingerprint_seed=seed,
                auto_geoip=bool(payload.get("auto_geoip", True)),
                platform=platform,
                browser_engine=engine,
                notes=notes,
                startup_url=normalize_startup_url(str(payload.get("startup_url") or "")),
                group_name=str(payload.get("group_name") or "").strip(),
                tags=str(payload.get("tags") or "").strip(),
                status="stopped",
                created_at=timestamp,
                updated_at=timestamp,
            )
            profile_user_data_dir(profile.id).mkdir(parents=True, exist_ok=True)
            profiles.append(profile)

        self.repository.create_profiles(profiles)
        self.load_profiles()
        for profile in profiles:
            self._log("profile.created_batch", profile)
        self.info_message.emit(f"Created {len(profiles)} profiles")
        return profiles

    def update_profile(
        self,
        profile_id: str,
        name: str,
        proxy: str | None,
        timezone: str,
        locale: str,
        screen_width: int,
        screen_height: int,
        fingerprint_seed: int | None = None,
        auto_geoip: bool = True,
        platform: str = "windows",
        notes: str = "",
        user_agent: str = "",
        extension_ids: list[str] | None = None,
        bookmark_ids: list[str] | None = None,
        browser_engine: str | None = None,
        startup_url: str = "",
        group_name: str | None = None,
        tags: str | None = None,
        pinned: bool | None = None,
    ) -> Profile:
        if profile_id in self.worker_threads:
            raise BrowserLaunchError("Stop the profile before editing it.")
        profile = self.repository.get_profile(profile_id)
        if not profile:
            raise ValueError("Profile does not exist.")
        if profile.deleted_at:
            raise ValueError("Profile is already in Trash.")
        profile.name = name.strip()
        profile.proxy = normalize_proxy(proxy) if proxy else None
        profile.timezone = timezone or DEFAULT_TIMEZONE
        profile.locale = locale or DEFAULT_LOCALE
        profile.screen_width = screen_width or DEFAULT_SCREEN_WIDTH
        profile.screen_height = screen_height or DEFAULT_SCREEN_HEIGHT
        if profile.seed_locked and fingerprint_seed and fingerprint_seed != profile.fingerprint_seed:
            raise BrowserLaunchError("Unlock the fingerprint seed before changing it.")
        profile.fingerprint_seed = fingerprint_seed or profile.fingerprint_seed
        profile.auto_geoip = auto_geoip
        profile.platform = platform
        profile.browser_engine = (
            browser_engine if browser_engine in {"cloak", "chrome"} else profile.browser_engine
        )
        if profile.browser_engine == "chrome":
            profile.platform = "windows"
            user_agent = ""
        profile.notes = notes.strip()
        profile.user_agent = user_agent.strip()
        profile.startup_url = normalize_startup_url(startup_url)
        if group_name is not None:
            profile.group_name = group_name.strip()
        if tags is not None:
            profile.tags = tags.strip()
        if pinned is not None:
            profile.pinned = bool(pinned)
        profile.extension_ids = extension_ids
        profile.bookmark_ids = bookmark_ids
        profile.updated_at = Profile.now_timestamp()
        self.repository.update_profile(profile)
        self.load_profiles()
        self._log("profile.updated", profile)
        self.info_message.emit(f"Updated profile {profile.name}")
        return profile

    def clone_profile(self, source_profile_id: str) -> Profile:
        source = self.repository.get_profile(source_profile_id)
        if not source:
            raise ValueError("Source profile does not exist.")
        return self.create_profile(
            name=f"{source.name} - Clone",
            proxy=source.proxy,
            timezone=source.timezone,
            locale=source.locale,
            screen_width=source.screen_width,
            screen_height=source.screen_height,
            fingerprint_seed=random.randint(100000, 999999999),
            auto_geoip=source.auto_geoip,
            platform=source.platform,
            notes=source.notes,
            user_agent=source.user_agent,
            extension_ids=source.extension_ids,
            bookmark_ids=source.bookmark_ids,
            browser_engine=source.browser_engine,
            startup_url=source.startup_url,
            group_name=source.group_name,
            tags=source.tags,
        )

    def bulk_update_profiles(self, profile_ids: list[str], updates: dict[str, object]) -> list[Profile]:
        profiles = [self.repository.get_profile(profile_id) for profile_id in dict.fromkeys(profile_ids)]
        profiles = [profile for profile in profiles if profile and not profile.deleted_at]
        if not profiles:
            raise ValueError("No profiles selected.")
        running = [profile.name for profile in profiles if profile.id in self.worker_threads or profile.status != "stopped"]
        if running:
            raise BrowserLaunchError(f"Stop these profiles before bulk editing: {', '.join(running[:5])}")
        snapshots = [replace(profile, extension_ids=list(profile.extension_ids) if profile.extension_ids is not None else None, bookmark_ids=list(profile.bookmark_ids) if profile.bookmark_ids is not None else None) for profile in profiles]
        resolved_updates = dict(updates)
        if resolved_updates.get("proxy") == "__best__":
            best = self.best_proxy()
            if not best:
                raise ValueError("Smart Proxy Pool has no live proxy available.")
            resolved_updates["proxy"] = best.url
        notes_mode = str(resolved_updates.pop("notes_mode", "replace"))
        for profile in profiles:
            if "group_name" in resolved_updates: profile.group_name = str(resolved_updates["group_name"] or "").strip()
            if "tags" in resolved_updates: profile.tags = str(resolved_updates["tags"] or "").strip()
            if "startup_url" in resolved_updates: profile.startup_url = normalize_startup_url(str(resolved_updates["startup_url"] or ""))
            if "proxy" in resolved_updates: profile.proxy = normalize_proxy(str(resolved_updates["proxy"] or "")) or None
            if "notes" in resolved_updates:
                text = str(resolved_updates["notes"] or "").strip()
                profile.notes = f"{profile.notes} · {text}".strip(" ·") if notes_mode == "append" and text else text
            if "extension_ids" in resolved_updates: profile.extension_ids = [str(item) for item in resolved_updates["extension_ids"]]  # type: ignore[arg-type]
            if "bookmark_ids" in resolved_updates: profile.bookmark_ids = [str(item) for item in resolved_updates["bookmark_ids"]]  # type: ignore[arg-type]
            profile.updated_at = Profile.now_timestamp()
            self.repository.update_profile(profile)
            self._log("profile.bulk_updated", profile, details=", ".join(sorted(updates)))
        self.load_profiles()
        self.info_message.emit(f"Updated {len(profiles)} profiles")
        return snapshots

    def restore_profile_snapshots(self, snapshots: list[Profile]) -> int:
        restored = 0
        for snapshot in snapshots:
            current = self.repository.get_profile(snapshot.id)
            if not current or current.deleted_at or current.status != "stopped":
                continue
            snapshot.status = "stopped"
            snapshot.updated_at = Profile.now_timestamp()
            self.repository.update_profile(snapshot)
            restored += 1
        if restored:
            self.load_profiles()
            self._log("profiles.bulk_undo", details=f"Restored {restored} profile(s)")
            self.info_message.emit(f"Restored {restored} profile changes")
        return restored

    def delete_profile(self, profile_id: str) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile:
            raise ValueError("Profile does not exist.")
        if profile.deleted_at:
            raise ValueError("Profile is already in Trash.")
        check_key = f"profile:{profile_id}"
        if check_key in self.proxy_check_threads:
            self.pending_delete_profile_ids.add(profile_id)
            self.close_profile(profile_id)
            self._move_profile_to_trash(profile_id, profile.name)
            return
        if profile_id in self.worker_threads:
            self.pending_delete_profile_ids.add(profile_id)
            self.close_profile(profile_id)
            self.info_message.emit(f"Closing profile {profile.name} before moving it to Trash...")
            return
        self._move_profile_to_trash(profile_id, profile.name)

    def restore_profile(self, profile_id: str) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile or not profile.deleted_at:
            raise ValueError("Profile is not in Trash.")
        self.repository.restore_profile(profile_id, Profile.now_timestamp())
        self.load_profiles()
        self.load_trash()
        self._log("profile.restored", profile)
        self.info_message.emit(f"Restored profile {profile.name}")

    def delete_profile_permanently(self, profile_id: str) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile or not profile.deleted_at:
            raise ValueError("Profile is not in Trash.")
        self._permanently_delete_profile(profile)
        self.load_trash()
        self._log("profile.deleted_permanently", profile, "warning")
        self.info_message.emit(f"Permanently deleted profile {profile.name}")

    def empty_trash(self) -> int:
        profiles = self.repository.list_deleted_profiles()
        for profile in profiles:
            self._log("profile.deleted_permanently", profile, "warning", "Empty Trash")
            self._permanently_delete_profile(profile)
        self.load_trash()
        if profiles:
            self.info_message.emit(f"Permanently deleted {len(profiles)} profile(s)")
        return len(profiles)

    def purge_expired_profiles(self) -> int:
        cutoff = datetime.utcnow() - timedelta(days=self.config_store.trash_retention_days())
        expired: list[Profile] = []
        for profile in self.repository.list_deleted_profiles():
            try:
                deleted_at = datetime.fromisoformat(profile.deleted_at)
            except (TypeError, ValueError):
                continue
            if deleted_at <= cutoff:
                expired.append(profile)
        for profile in expired:
            self._log("profile.deleted_expired", profile, "warning")
            self._permanently_delete_profile(profile)
        if expired:
            self.load_trash()
        return len(expired)

    def update_profile_metadata(self, profile_id: str, field: str, value: object) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile or profile.deleted_at:
            raise ValueError("Profile does not exist.")
        self.repository.update_metadata(profile_id, field, value, Profile.now_timestamp())
        refreshed = self.repository.get_profile(profile_id)
        self.load_profiles()
        self._log(f"profile.{field}_updated", refreshed or profile)

    def close_all_profiles(self) -> int:
        profile_ids = list(self.workers)
        checking_ids = [key.split(":", 1)[1] for key in self.proxy_check_threads if key.startswith("profile:")]
        for profile_id in profile_ids:
            self.close_profile(profile_id, silent=True)
        for key in list(self.proxy_check_threads):
            if key.startswith("profile:"):
                profile_id = key.split(":", 1)[1]
                self.close_profile(profile_id, silent=True)
        total = len(set(profile_ids + checking_ids))
        if total:
            self._log("profiles.close_all", details=f"Requested stop for {total} profile(s)")
        return total

    def reconcile_profile_statuses(self) -> None:
        active = set(self.worker_threads)
        checking = {
            key.split(":", 1)[1] for key in self.proxy_check_threads if key.startswith("profile:")
        }
        changed = False
        for profile in self.repository.list_profiles():
            if profile.status != "stopped" and profile.id not in active and profile.id not in checking:
                self.repository.update_status(profile.id, "stopped", Profile.now_timestamp())
                changed = True
        if changed:
            self.load_profiles()

    def check_profile_health(self, profile_id: str) -> None:
        if profile_id in self.health_threads:
            return
        profile = self.repository.get_profile(profile_id)
        if not profile or profile.deleted_at:
            raise ValueError("Profile does not exist.")
        worker = ProfileHealthWorker(profile)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_health_result)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(partial(self._cleanup_health_worker, profile_id))
        thread.finished.connect(thread.deleteLater)
        self.health_workers[profile_id] = worker
        self.health_threads[profile_id] = thread
        thread.start()
        self.info_message.emit(f"Checking {profile.name}...")

    def check_all_profile_health(self) -> None:
        profiles = self.repository.list_profiles()
        for profile in profiles:
            self.check_profile_health(profile.id)
        self.info_message.emit(f"Checking {len(profiles)} profile(s)...")

    def _cleanup_health_worker(self, profile_id: str) -> None:
        self.health_workers.pop(profile_id, None)
        self.health_threads.pop(profile_id, None)

    def _handle_health_result(self, profile_id: str, payload: dict) -> None:
        profile = self.repository.get_profile(profile_id)
        if not profile:
            return
        timestamp = str(payload["timestamp"])
        status = str(payload["status"])
        self.repository.update_health(profile_id, status, timestamp)
        self.maintenance_repository.save_health(
            profile.id, profile.name, status, str(payload["summary"]),
            dict(payload["details"]), timestamp,
        )
        self._log("profile.health_checked", profile, "error" if status == "fail" else "info", str(payload["summary"]))
        self.load_health()
        self.load_profiles()

    def _start_maintenance(self, key: str, operation) -> None:
        if key in self.maintenance_threads:
            raise RuntimeError("This maintenance task is already running.")
        worker = MaintenanceWorker(key, operation)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_maintenance_finished)
        worker.failed.connect(self._handle_maintenance_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(partial(self._cleanup_maintenance, key))
        thread.finished.connect(thread.deleteLater)
        self.maintenance_workers[key] = worker
        self.maintenance_threads[key] = thread
        self.task_started.emit(key, key.replace("-", " ").title(), "Background operation")
        thread.start()

    def _cleanup_maintenance(self, key: str) -> None:
        self.maintenance_workers.pop(key, None)
        self.maintenance_threads.pop(key, None)

    def create_backup(self, destination: str | None = None, automatic: bool = False) -> None:
        if self.worker_threads or any(key.startswith("profile:") for key in self.proxy_check_threads):
            if automatic:
                return
            raise BrowserLaunchError("Close all profiles before creating a complete backup.")
        key = "backup"
        def operation():
            result = create_full_backup(destination)
            prune_backups(10)
            return {"path": str(result), "automatic": automatic}
        self._start_maintenance(key, operation)
        self.info_message.emit("Creating backup...")

    def restore_backup(self, source: str) -> None:
        if self.has_background_work():
            raise BrowserLaunchError("Stop all running profiles before restoring a backup.")
        safety = create_full_backup()
        self._log("backup.safety_created", details=str(safety))
        self._start_maintenance("restore", lambda: restore_full_backup(source))
        self.info_message.emit("Restoring backup...")

    def run_automatic_backup_if_due(self) -> None:
        if not self.config_store.automatic_backup_enabled() or "backup" in self.maintenance_threads or self.worker_threads:
            return
        last = self.config_store.last_backup_at()
        try:
            last_time = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            last_time = datetime.min
        if datetime.utcnow() - last_time >= timedelta(days=self.config_store.backup_interval_days()):
            self.create_backup(automatic=True)

    def _handle_maintenance_finished(self, key: str, result: object) -> None:
        self.task_finished.emit(key, True, str(result or "Completed"))
        if key == "backup":
            payload = dict(result or {})
            path = str(payload.get("path") or "")
            self.config_store.set_last_backup_at(Profile.now_timestamp())
            self._log("backup.created", details=path)
            self.backup_completed.emit(path)
            if not payload.get("automatic"):
                self.info_message.emit(f"Backup created: {path}")
        elif key == "restore":
            self._log("backup.restored")
            self.restore_completed.emit()
            self.load_profiles(); self.load_trash(); self.load_proxies(); self.load_extensions(); self.load_bookmarks()
            self.info_message.emit("Backup restored. Restart the app to reload all settings.")
        elif key == "cloak_update":
            new_version = str(result or "")
            if new_version:
                self.config_store.set_cloak_browser_version(new_version)
                self._log("cloak.updated", details=new_version)
                self.info_message.emit(f"CloakBrowser {new_version} downloaded and selected")
            else:
                self.info_message.emit("CloakBrowser is already up to date")
            self.load_fingerprint_lab()

    def _handle_maintenance_failed(self, key: str, message: str) -> None:
        self.task_finished.emit(key, False, message)
        self.maintenance_repository.log(f"{key}.failed", severity="error", details=message)
        self.load_activity()
        self.operation_failed.emit(message)

    def export_profile_archive(self, profile_id: str, destination: str) -> str:
        profile = self.repository.get_profile(profile_id)
        if not profile or profile.deleted_at:
            raise ValueError("Profile does not exist.")
        path = export_profile(profile, destination)
        self._log("profile.exported", profile, details=str(path))
        return str(path)

    def import_profile_archive(self, source: str) -> Profile:
        new_id = str(uuid.uuid4())
        base_name = Path(source).stem.replace("-profile", "") or "Imported Profile"
        existing_names = {item.name.casefold() for item in self.repository.list_profiles()}
        name = base_name
        counter = 2
        while name.casefold() in existing_names:
            name = f"{base_name} {counter}"
            counter += 1
        profile, temp = read_imported_profile(source, new_id, name)
        try:
            self.repository.create_profile(profile)
            finish_profile_import(temp, profile.id)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            self.repository.delete_profile(profile.id)
            raise
        self.load_profiles()
        self._log("profile.imported", profile, details=source)
        return profile

    def export_activity_report(self, destination: str) -> str:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = self.maintenance_repository.list_activity(10000)
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp", "severity", "action", "profile_name", "profile_id", "details"])
            writer.writeheader()
            writer.writerows({key: record.get(key, "") for key in writer.fieldnames} for record in records)
        self._log("activity.exported", details=str(path))
        return str(path)

    def open_profile(self, profile_id: str) -> None:
        check_key = f"profile:{profile_id}"
        if profile_id in self.worker_threads or check_key in self.proxy_check_threads:
            raise BrowserLaunchError("Profile is running or starting.")
        profile = self.repository.get_profile(profile_id)
        if not profile:
            raise ValueError("Profile does not exist.")
        if profile.deleted_at:
            raise BrowserLaunchError("Restore this profile from Trash before opening it.")

        report = self.profile_compatibility(profile_id)
        if report.blockers:
            self._log("profile.compatibility_blocked", profile, "warning", blocker_message(report))
            raise BrowserLaunchError(blocker_message(report))
        if report.warnings:
            self.info_message.emit(
                f"Compatibility Guard · {report.score}/100 · {len(report.warnings)} warning(s)"
            )

        self._log("profile.open_requested", profile)
        self.task_started.emit(f"profile-open:{profile.id}", f"Open {profile.name}", "Preparing browser")

        if profile.proxy:
            self.repository.update_status(profile_id, "checking", Profile.now_timestamp())
            self.proxy_repository.update_check_result_by_url(profile.proxy, "checking")
            self.load_profiles()
            self.load_proxies()
            self._start_proxy_check("profile", profile_id, profile.proxy)
            self.info_message.emit(f"Checking proxy for {profile.name}...")
            return
        try:
            self._start_browser(profile)
        except Exception as error:
            self.task_finished.emit(f"profile-open:{profile.id}", False, str(error))
            raise

    def profile_compatibility(self, profile_id: str):
        profile = self.repository.get_profile(profile_id)
        if not profile:
            raise ValueError("Profile does not exist.")
        proxy_record = next((item for item in self.proxy_repository.list_all() if item.url == profile.proxy), None)
        return check_profile_compatibility(
            profile,
            proxy_record=proxy_record,
            all_profiles=self.repository.list_profiles(),
            version_info=self.cloak_version_info() if profile.browser_engine == "cloak" else None,
        )

    def _start_browser(self, profile: Profile) -> None:
        profile_id = profile.id
        if profile_id in self.worker_threads:
            return

        extension_paths = [str(self._profile_bookmark_extension(profile))]
        selected_extensions = None if profile.extension_ids is None else set(profile.extension_ids)
        extension_paths.extend(
            item.path for item in self.extension_repository.list_all()
            if item.enabled
            and (selected_extensions is None or item.id in selected_extensions)
            and Path(item.path).is_dir()
        )
        effective_profile = self.effective_profile(profile)
        worker = BrowserSessionWorker(effective_profile, extension_paths)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.opened.connect(self._handle_opened)
        worker.closed.connect(self._handle_closed)
        worker.failed.connect(self._handle_failed)
        worker.closed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.workers[profile_id] = worker
        self.worker_threads[profile_id] = thread
        self.repository.update_status(profile_id, "starting", Profile.now_timestamp())
        self.load_profiles()
        thread.start()

    def effective_profile(self, profile: Profile) -> Profile:
        """Apply app-wide defaults without changing the stored profile override."""
        return replace(
            profile,
            startup_url=profile.startup_url or self.config_store.default_startup_url(),
            cloak_version=self.config_store.cloak_browser_version(),
        )

    def _start_proxy_check(self, kind: str, target_id: str, proxy_url: str) -> None:
        key = f"{kind}:{target_id}"
        if key in self.proxy_check_threads:
            return
        worker = ProxyCheckWorker(kind, target_id, proxy_url)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_proxy_check_result)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(partial(self._cleanup_proxy_check, key))
        thread.finished.connect(thread.deleteLater)
        self.proxy_check_workers[key] = worker
        self.proxy_check_threads[key] = thread
        thread.start()

    def _cleanup_proxy_check(self, key: str) -> None:
        self.proxy_check_workers.pop(key, None)
        self.proxy_check_threads.pop(key, None)

    def _handle_proxy_check_result(
        self, kind: str, target_id: str, result: ProxyCheckResult
    ) -> None:
        key = f"{kind}:{target_id}"
        cancelled = key in self.cancelled_proxy_checks
        self.cancelled_proxy_checks.discard(key)
        status = "live" if result.alive else "dead"
        if kind == "proxy":
            self.proxy_repository.update_check_result(
                target_id, status, result.latency_ms, result.exit_ip,
                result.checked_at, result.error, result.location,
                result.country_code, result.timezone,
            )
            self.load_proxies()
            record = self.proxy_repository.get(target_id)
            self._log("proxy.checked", severity="info" if result.alive else "warning", details=f"{record.name if record else target_id}: {result.exit_ip or result.error}")
            if result.alive:
                location_text = f" · {result.location}" if result.location else ""
                self.info_message.emit(f"Proxy is live · {result.latency_ms} ms · {result.exit_ip}{location_text}")
            else:
                self.info_message.emit(f"Proxy is dead · {result.error}")
            self._update_proxy_batch_task(target_id)
            return

        profile = self.repository.get_profile(target_id)
        if profile and profile.proxy:
            self.proxy_repository.update_check_result_by_url(
                profile.proxy, status, result.latency_ms, result.exit_ip,
                result.checked_at, result.error, result.location,
                result.country_code, result.timezone,
            )
        self.load_proxies()
        if cancelled or not profile:
            if profile:
                self.repository.update_status(target_id, "stopped", Profile.now_timestamp())
                self.load_profiles()
            return
        if not result.alive:
            self.repository.update_status(target_id, "stopped", Profile.now_timestamp())
            self.load_profiles()
            self.operation_failed.emit(
                f"Cannot open {profile.name}: proxy is not live.\n{result.error}"
            )
            self.task_finished.emit(f"profile-open:{profile.id}", False, result.error or "Proxy is not live")
            return
        self.info_message.emit(
            f"Proxy live · {result.latency_ms} ms · {result.exit_ip}"
            f"{' · ' + result.location if result.location else ''}. Opening {profile.name}..."
        )
        try:
            self._start_browser(profile)
        except Exception as error:
            self.repository.update_status(target_id, "stopped", Profile.now_timestamp())
            self.load_profiles()
            self.operation_failed.emit(f"Could not open {profile.name}: {error}")
            self.task_finished.emit(f"profile-open:{profile.id}", False, str(error))

    def _profile_bookmark_extension(self, profile: Profile) -> Path:
        source = builtin_extension_dir()
        # A versioned path changes the unpacked extension ID and prevents
        # Chromium from reusing a cached Manifest V3 service worker.
        target = profile_user_data_dir(profile.id) / ".cloak-profile-tools-v2"
        shutil.copytree(source, target, dirs_exist_ok=True)
        selected_ids = None if profile.bookmark_ids is None else set(profile.bookmark_ids)
        bookmarks = [
            item for item in self.bookmark_repository.list_all()
            if selected_ids is None or item.id in selected_ids
        ]
        write_bookmark_config(target, bookmarks, profile.name)
        return target

    def close_profile(self, profile_id: str, silent: bool = False) -> None:
        check_key = f"profile:{profile_id}"
        if check_key in self.proxy_check_threads:
            self.cancelled_proxy_checks.add(check_key)
            self.repository.update_status(profile_id, "stopped", Profile.now_timestamp())
            self.load_profiles()
            return
        worker = self.workers.get(profile_id)
        if worker is None:
            if not silent:
                raise BrowserLaunchError("Profile is not running.")
            return
        self.repository.update_status(profile_id, "stopping", Profile.now_timestamp())
        self.load_profiles()
        worker.request_stop()

    def shutdown(self) -> None:
        for worker in list(self.workers.values()):
            worker.request_stop()
        self.cancelled_proxy_checks.update(
            key for key in self.proxy_check_threads if key.startswith("profile:")
        )

    def has_background_work(self) -> bool:
        return bool(self.worker_threads or self.proxy_check_threads or self.health_threads or self.maintenance_threads)

    def _move_profile_to_trash(self, profile_id: str, profile_name: str) -> None:
        profile = self.repository.get_profile(profile_id)
        self.repository.move_to_trash(profile_id, Profile.now_timestamp())
        self.pending_delete_profile_ids.discard(profile_id)
        self.load_profiles()
        self.load_trash()
        self._log("profile.moved_to_trash", profile)
        self.info_message.emit(f"Moved profile {profile_name} to Trash")

    def _permanently_delete_profile(self, profile: Profile) -> None:
        self.repository.delete_profile(profile.id)
        shutil.rmtree(profile_user_data_dir(profile.id), ignore_errors=True)

    def _handle_opened(self, profile_id: str) -> None:
        worker = self.workers.get(profile_id)
        if worker:
            self.running_profiles[profile_id] = worker
        self.repository.update_status(profile_id, "running", Profile.now_timestamp())
        self.repository.mark_used(profile_id, Profile.now_timestamp())
        profile = self.repository.get_profile(profile_id)
        if profile and profile.browser_engine == "cloak" and not profile.seed_locked:
            self.repository.set_seed_locked(profile_id, True, Profile.now_timestamp())
            profile.seed_locked = True
        if profile and self.maintenance_repository.latest_baseline(profile_id) is None:
            try:
                self.create_fingerprint_snapshot(profile_id)
            except Exception as error:
                self.maintenance_repository.log("fingerprint.snapshot_failed", profile_id=profile.id, profile_name=profile.name, severity="warning", details=str(error))
        self._log("profile.opened", profile)
        self.load_profiles()
        self.profile_opened.emit(profile_id)
        self.task_finished.emit(f"profile-open:{profile_id}", True, "Browser opened")

    def _cleanup_session(self, profile_id: str) -> None:
        self.running_profiles.pop(profile_id, None)
        self.workers.pop(profile_id, None)
        self.worker_threads.pop(profile_id, None)

    def _handle_closed(self, profile_id: str) -> None:
        profile = self.repository.get_profile(profile_id)
        profile_name = profile.name if profile else profile_id
        self._cleanup_session(profile_id)
        self.repository.update_status(profile_id, "stopped", Profile.now_timestamp())
        if profile_id in self.pending_delete_profile_ids:
            self._move_profile_to_trash(profile_id, profile_name)
            return
        self.load_profiles()
        self._log("profile.closed", profile)
        self.profile_closed.emit(profile_id)

    def _handle_failed(self, profile_id: str, error_message: str) -> None:
        self._cleanup_session(profile_id)
        pending_delete = profile_id in self.pending_delete_profile_ids
        self.repository.update_status(profile_id, "stopped", Profile.now_timestamp())
        if pending_delete:
            profile = self.repository.get_profile(profile_id)
            self._move_profile_to_trash(profile_id, profile.name if profile else profile_id)
            return
        self.load_profiles()
        profile = self.repository.get_profile(profile_id)
        self._log("profile.failed", profile, "error", error_message)
        self.operation_failed.emit(error_message)
        self.task_finished.emit(f"profile-open:{profile_id}", False, error_message)
