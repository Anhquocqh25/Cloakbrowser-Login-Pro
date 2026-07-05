from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models.profile import Profile
from utils.proxy_parser import parse_proxy


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    status: str
    score: int
    summary: str
    checks: list[dict[str, str]]


def snapshot_data(profile: Profile, version_info: dict[str, Any] | None = None) -> dict[str, Any]:
    version_info = version_info or {}
    proxy_scheme = "direct"
    if profile.proxy:
        try:
            parsed = parse_proxy(profile.proxy)
            proxy_scheme = parsed.scheme if parsed else "invalid"
        except ValueError:
            proxy_scheme = "invalid"
    return {
        "engine": profile.browser_engine,
        "cloak_version": profile.cloak_version or str(version_info.get("version") or ""),
        "cloak_tier": str(version_info.get("tier") or ""),
        "fingerprint_seed": profile.fingerprint_seed,
        "seed_locked": profile.seed_locked,
        "platform": profile.platform,
        "screen": [profile.screen_width, profile.screen_height],
        "locale": profile.locale,
        "timezone": profile.timezone,
        "auto_geoip": profile.auto_geoip,
        "user_agent": profile.user_agent.strip() or "generated-by-engine",
        "proxy_mode": proxy_scheme,
        "webrtc_policy": "proxy-only" if profile.proxy else "system-default",
        "dns_route": "proxy-bridge" if profile.proxy else "system",
        "extensions": sorted(profile.extension_ids or []),
    }


def fingerprint_hash(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            differences[key] = {"before": before.get(key), "after": after.get(key)}
    return differences


def regression_status(differences: dict[str, Any]) -> str:
    critical = {"engine", "fingerprint_seed", "platform", "screen", "user_agent"}
    warning = {"cloak_version", "locale", "timezone", "auto_geoip", "proxy_mode", "webrtc_policy", "dns_route", "extensions"}
    keys = set(differences)
    if keys & critical:
        return "fail"
    if keys & warning:
        return "warning"
    return "pass"


def check_consistency(profile: Profile, version_info: dict[str, Any] | None = None) -> ConsistencyReport:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, message: str) -> None:
        checks.append({"name": name, "status": status, "message": message})

    if profile.browser_engine == "cloak":
        if profile.fingerprint_seed and 100000 <= profile.fingerprint_seed <= 999999999:
            add("Seed", "pass", "Valid persistent fingerprint seed")
        else:
            add("Seed", "fail", "Fingerprint seed is missing or outside the supported range")
        add("Seed lock", "pass" if profile.seed_locked else "warning", "Locked" if profile.seed_locked else "Not locked yet")
        installed = bool((version_info or {}).get("installed"))
        add("Cloak core", "pass" if installed else "fail", str((version_info or {}).get("version") or "Binary not installed"))
    else:
        add("Engine", "warning", "Native Chrome uses a natural, unmanaged fingerprint")

    expected_tokens = {
        "windows": ("windows nt",),
        "macos": ("macintosh", "mac os x"),
        "linux": ("x11", "linux"),
    }
    ua = profile.user_agent.strip().casefold()
    if not ua:
        add("User-Agent", "pass", "Generated consistently by browser engine")
    elif any(token in ua for token in expected_tokens.get(profile.platform, ())):
        add("User-Agent", "pass", f"Matches {profile.platform}")
    else:
        add("User-Agent", "fail", f"Custom User-Agent does not match {profile.platform}")

    width, height = profile.screen_width, profile.screen_height
    if 800 <= width <= 5120 and 600 <= height <= 2880 and width >= height:
        add("Screen", "pass", f"{width}×{height} desktop geometry")
    else:
        add("Screen", "warning", f"Unusual desktop geometry: {width}×{height}")

    locale_ok = bool(re.fullmatch(r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z]{2,4})?", profile.locale or ""))
    add("Locale", "pass" if locale_ok else "warning", profile.locale or "Locale is empty")
    try:
        ZoneInfo(profile.timezone)
        add("Timezone", "pass", profile.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        # Windows Python installations may not ship the IANA tzdata database.
        # Keep validating the identifier shape instead of reporting a false
        # mismatch for values such as Asia/Bangkok.
        timezone_shape_ok = bool(re.fullmatch(r"[A-Za-z_+-]+(?:/[A-Za-z0-9_+.-]+)+", profile.timezone or ""))
        add("Timezone", "pass" if timezone_shape_ok else "fail", profile.timezone if timezone_shape_ok else f"Unknown timezone: {profile.timezone}")

    if profile.proxy:
        try:
            parsed = parse_proxy(profile.proxy)
            add("Proxy", "pass" if parsed else "fail", parsed.scheme.upper() if parsed else "Invalid proxy")
        except ValueError as error:
            add("Proxy", "fail", str(error))
        add("Location sync", "pass" if profile.auto_geoip else "warning", "Based on proxy" if profile.auto_geoip else "Manual locale/timezone")
        add("WebRTC/DNS", "pass", "Proxy bridge isolation configured")
    else:
        add("Proxy", "warning", "Direct connection uses machine network identity")
        if profile.auto_geoip:
            add("Location sync", "warning", "Based-on-proxy is enabled without a proxy")

    weights = {"pass": 1.0, "warning": 0.55, "fail": 0.0}
    score = round(sum(weights[item["status"]] for item in checks) / max(1, len(checks)) * 100)
    statuses = {item["status"] for item in checks}
    status = "fail" if "fail" in statuses else ("warning" if "warning" in statuses else "pass")
    return ConsistencyReport(status, score, f"{score}/100 · {len(checks)} checks", checks)


def detect_duplicates(profiles: list[Profile], version_info: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {profile.id: [] for profile in profiles}
    by_seed: dict[int, list[Profile]] = {}
    by_hash: dict[str, list[Profile]] = {}
    for profile in profiles:
        if profile.fingerprint_seed is not None and profile.browser_engine == "cloak":
            by_seed.setdefault(profile.fingerprint_seed, []).append(profile)
        stable = snapshot_data(profile, version_info)
        stable.pop("fingerprint_seed", None)
        stable.pop("seed_locked", None)
        stable.pop("proxy_mode", None)
        stable.pop("webrtc_policy", None)
        stable.pop("dns_route", None)
        by_hash.setdefault(fingerprint_hash(stable), []).append(profile)

    def connect(group: list[Profile], reason: str, severity: str) -> None:
        if len(group) < 2:
            return
        for profile in group:
            for other in group:
                if other.id != profile.id:
                    results[profile.id].append({"profile_id": other.id, "name": other.name, "reason": reason, "severity": severity})

    for group in by_seed.values():
        connect(group, "Same fingerprint seed", "fail")
    for group in by_hash.values():
        connect(group, "Same browser/hardware configuration", "warning")
    for profile_id, items in list(results.items()):
        merged: dict[str, dict[str, Any]] = {}
        for item in items:
            other_id = str(item["profile_id"])
            if other_id not in merged:
                merged[other_id] = dict(item)
            elif item["reason"] not in merged[other_id]["reason"]:
                merged[other_id]["reason"] += f"; {item['reason']}"
                if item["severity"] == "fail":
                    merged[other_id]["severity"] = "fail"
        results[profile_id] = list(merged.values())
    return results
