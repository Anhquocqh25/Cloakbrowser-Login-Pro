from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import hashlib
import json
from typing import Any

from config import (
    APP_VERSION,
    DEFAULT_LOCALE,
    DEFAULT_SCREEN_HEIGHT,
    DEFAULT_SCREEN_WIDTH,
    DEFAULT_TIMEZONE,
)
from models.profile import Profile
from utils.paths import profile_user_data_dir
from utils.secret_store import decrypt_proxy_field, encrypt_proxy_field


SIDECAR_FILE = "profile.json"
SIDECAR_SCHEMA = 1


def _profile_payload(profile: Profile) -> dict[str, Any]:
    payload = asdict(profile)
    payload.pop("cloak_version", None)
    # Keep proxy credentials out of plain sidecar JSON on disk.
    if payload.get("proxy"):
        try:
            payload["proxy"] = encrypt_proxy_field(str(payload["proxy"]))
        except OSError:
            payload["proxy"] = None
    # Runtime states should not be trusted after a restart or DB recovery.
    if payload.get("status") not in {"stopped", "checking", "starting", "running", "stopping"}:
        payload["status"] = "stopped"
    if payload.get("status") != "stopped":
        payload["status"] = "stopped"
    return payload


def write_profile_sidecar(profile: Profile) -> None:
    directory = profile_user_data_dir(profile.id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SIDECAR_SCHEMA,
        "app_version": APP_VERSION,
        "profile": _profile_payload(profile),
    }
    target = directory / SIDECAR_FILE
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def read_profile_sidecar(directory: Path) -> dict[str, Any] | None:
    target = directory / SIDECAR_FILE
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    profile = payload.get("profile") if isinstance(payload, dict) else None
    return profile if isinstance(profile, dict) else None


def profile_directory_has_browser_data(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    markers = (
        directory / "Local State",
        directory / "Preferences",
        directory / "Default" / "Preferences",
        directory / "Default" / "Cookies",
        directory / "Default" / "Network" / "Cookies",
        directory / "Network" / "Cookies",
    )
    if any(marker.exists() for marker in markers):
        return True
    try:
        return any(item.is_file() for item in directory.rglob("*") if item.name != SIDECAR_FILE)
    except OSError:
        return False


def deterministic_seed(profile_id: str) -> int:
    digest = hashlib.sha256(profile_id.encode("utf-8", errors="ignore")).hexdigest()
    return 100000 + (int(digest[:12], 16) % 899900000)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def profile_from_sidecar_or_directory(
    directory: Path,
    existing_names: set[str],
    used_seeds: set[int],
    recovered_index: int,
) -> Profile | None:
    if not directory.is_dir():
        return None
    profile_id = directory.name
    sidecar = read_profile_sidecar(directory)
    if sidecar is None and not profile_directory_has_browser_data(directory):
        return None

    allowed = set(Profile.__dataclass_fields__) - {"cloak_version"}
    payload = {key: value for key, value in (sidecar or {}).items() if key in allowed}
    payload["id"] = profile_id

    fallback_name = f"Recovered Profile {recovered_index:02d}"
    name = str(payload.get("name") or fallback_name).strip() or fallback_name
    if name.casefold() in existing_names:
        suffix = 2
        base = name
        while f"{base} {suffix}".casefold() in existing_names:
            suffix += 1
        name = f"{base} {suffix}"
    existing_names.add(name.casefold())

    seed = payload.get("fingerprint_seed")
    try:
        seed = int(seed) if seed else deterministic_seed(profile_id)
    except (TypeError, ValueError):
        seed = deterministic_seed(profile_id)
    while seed in used_seeds:
        seed += 1
    used_seeds.add(seed)

    timestamp = Profile.now_timestamp()
    browser_engine = str(payload.get("browser_engine") or "cloak")
    if browser_engine not in {"cloak", "chrome"}:
        browser_engine = "cloak"
    raw_proxy = str(payload.get("proxy") or "").strip() or None
    if raw_proxy:
        try:
            raw_proxy = decrypt_proxy_field(raw_proxy)
        except OSError:
            # Leave encrypted/unreadable value as None rather than crashing recovery.
            raw_proxy = None
    profile = Profile(
        id=profile_id,
        name=name,
        proxy=raw_proxy,
        timezone=str(payload.get("timezone") or DEFAULT_TIMEZONE),
        locale=str(payload.get("locale") or DEFAULT_LOCALE),
        screen_width=_safe_int(payload.get("screen_width"), DEFAULT_SCREEN_WIDTH),
        screen_height=_safe_int(payload.get("screen_height"), DEFAULT_SCREEN_HEIGHT),
        fingerprint_seed=seed,
        auto_geoip=bool(payload.get("auto_geoip", True)),
        platform=str(payload.get("platform") or "windows"),
        browser_engine=browser_engine,
        notes=str(payload.get("notes") or "Recovered from existing browser data").strip(),
        user_agent=str(payload.get("user_agent") or ""),
        startup_url=str(payload.get("startup_url") or ""),
        extension_ids=payload.get("extension_ids") if isinstance(payload.get("extension_ids"), list) else None,
        bookmark_ids=payload.get("bookmark_ids") if isinstance(payload.get("bookmark_ids"), list) else None,
        status="stopped",
        deleted_at=str(payload.get("deleted_at") or ""),
        group_name=str(payload.get("group_name") or ""),
        tags=str(payload.get("tags") or ""),
        pinned=bool(payload.get("pinned", False)),
        last_used_at=str(payload.get("last_used_at") or ""),
        health_status=str(payload.get("health_status") or "unknown"),
        health_checked_at=str(payload.get("health_checked_at") or ""),
        seed_locked=bool(payload.get("seed_locked", False)),
        created_at=str(payload.get("created_at") or timestamp),
        updated_at=str(payload.get("updated_at") or timestamp),
    )
    return profile
