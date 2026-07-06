from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from models.profile import Profile
from models.proxy import ProxyRecord
from utils.proxy_parser import parse_proxy


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    key: str
    severity: str
    title: str
    detail: str
    fix: str = ""


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: str
    score: int
    issues: tuple[CompatibilityIssue, ...]

    @property
    def blockers(self) -> tuple[CompatibilityIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "blocker")

    @property
    def warnings(self) -> tuple[CompatibilityIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "warning")


def check_profile_compatibility(
    profile: Profile,
    *,
    proxy_record: ProxyRecord | None = None,
    all_profiles: list[Profile] | None = None,
    version_info: dict[str, Any] | None = None,
) -> CompatibilityReport:
    issues: list[CompatibilityIssue] = []

    def add(key: str, severity: str, title: str, detail: str, fix: str = "") -> None:
        issues.append(CompatibilityIssue(key, severity, title, detail, fix))

    if profile.platform not in {"windows", "macos", "linux"}:
        add("platform", "blocker", "Unsupported platform", profile.platform, "Choose Windows, macOS or Linux.")
    if profile.browser_engine == "cloak":
        if not profile.fingerprint_seed or not 100000 <= profile.fingerprint_seed <= 999999999:
            add("seed", "blocker", "Invalid fingerprint seed", "A stable CloakBrowser seed is required.", "Regenerate the seed in Advanced settings.")
        if version_info is not None and not bool(version_info.get("installed")):
            add("core", "warning", "CloakBrowser core is not cached yet", str(version_info.get("error") or "It will be downloaded at first launch"), "Keep the internet connected for first launch.")

    duplicates = [
        item for item in (all_profiles or [])
        if item.id != profile.id and item.browser_engine == "cloak"
        and item.fingerprint_seed == profile.fingerprint_seed
    ]
    if profile.browser_engine == "cloak" and duplicates:
        add("duplicate_seed", "blocker", "Duplicate fingerprint seed", f"Also used by: {', '.join(item.name for item in duplicates[:4])}", "Regenerate this profile seed.")

    expected_tokens = {
        "windows": ("windows nt",), "macos": ("macintosh", "mac os x"), "linux": ("x11", "linux"),
    }
    ua = profile.user_agent.strip().casefold()
    if ua and not any(token in ua for token in expected_tokens.get(profile.platform, ())):
        add("user_agent", "blocker", "User-Agent and OS conflict", f"The custom User-Agent does not represent {profile.platform}.", "Clear the custom User-Agent or select the matching OS.")
    if ua:
        version_match = re.search(r"chrome/(\d+)", ua)
        core_version = str((version_info or {}).get("version") or "")
        core_major = re.search(r"\d+", core_version)
        if version_match and core_major and version_match.group(1) != core_major.group(0):
            add("browser_version", "warning", "Browser version mismatch", f"User-Agent Chrome/{version_match.group(1)} vs core {core_major.group(0)}.", "Use the engine-generated User-Agent.")

    if not (800 <= profile.screen_width <= 5120 and 600 <= profile.screen_height <= 2880 and profile.screen_width >= profile.screen_height):
        add("screen", "blocker", "Unsupported screen geometry", profile.screen_size_label, "Choose a common desktop resolution.")
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z]{2,4})?", profile.locale or ""):
        add("locale", "warning", "Unusual locale", profile.locale or "Empty", "Choose a locale from the list.")
    if not re.fullmatch(r"[A-Za-z_+-]+(?:/[A-Za-z0-9_+.-]+)+", profile.timezone or ""):
        add("timezone", "blocker", "Invalid timezone", profile.timezone or "Empty", "Choose an IANA timezone from the list.")

    if profile.proxy:
        try:
            if parse_proxy(profile.proxy) is None:
                raise ValueError("Invalid proxy")
        except ValueError as error:
            add("proxy", "blocker", "Invalid proxy", str(error), "Edit or remove this proxy.")
        if proxy_record:
            if not proxy_record.enabled:
                add("proxy_disabled", "blocker", "Proxy disabled by Smart Pool", proxy_record.check_error or proxy_record.name, "Recheck or enable the proxy.")
            elif proxy_record.status == "dead":
                add("proxy_dead", "blocker", "Proxy is offline", proxy_record.check_error or proxy_record.name, "Choose another live proxy.")
            elif proxy_record.status not in {"live", "checking"}:
                add("proxy_unknown", "warning", "Proxy has not been verified", proxy_record.name, "Check the proxy before launch.")
            if proxy_record.last_checked_at:
                try:
                    checked = datetime.fromisoformat(proxy_record.last_checked_at)
                    if checked < datetime.utcnow() - timedelta(hours=2):
                        add("proxy_stale", "warning", "Proxy result is stale", proxy_record.last_checked_at.replace("T", " "), "Run a fresh proxy check.")
                except ValueError:
                    pass
            if not profile.auto_geoip and proxy_record.timezone and profile.timezone != proxy_record.timezone:
                add("timezone_proxy", "warning", "Timezone differs from proxy", f"Profile {profile.timezone} · proxy {proxy_record.timezone}", "Enable Based on proxy.")
        if not profile.auto_geoip:
            add("geo_sync", "warning", "Proxy location sync is off", "Locale, timezone and WebRTC will use manual values.", "Enable Based on proxy.")
    else:
        add("direct", "warning", "Direct connection", "The profile will use the machine network identity.")

    blockers = sum(item.severity == "blocker" for item in issues)
    warnings = sum(item.severity == "warning" for item in issues)
    score = max(0, 100 - blockers * 35 - warnings * 8)
    status = "blocked" if blockers else ("warning" if warnings else "ready")
    return CompatibilityReport(status, score, tuple(issues))


def blocker_message(report: CompatibilityReport) -> str:
    lines = ["Fingerprint Compatibility Guard blocked launch:"]
    lines.extend(f"• {issue.title}: {issue.detail}" for issue in report.blockers)
    lines.append("Open profile Settings to fix these items.")
    return "\n".join(lines)
