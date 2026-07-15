from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from models.profile import Profile
from models.proxy import ProxyRecord
from utils.geo_options import country_to_locale
from utils.proxy_parser import parse_proxy
from utils.timeutil import is_older_than
from utils.user_agent import chrome_major_from_user_agent, user_agent_platform


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

    ua = profile.user_agent.strip().casefold()
    if ua:
        ua_platform = user_agent_platform(ua)
        if ua_platform and ua_platform != profile.platform:
            add("user_agent", "blocker", "User-Agent and OS conflict", f"The custom User-Agent represents {ua_platform}, but the profile OS is {profile.platform}.", "Clear the custom User-Agent or select the matching OS.")
        elif not ua_platform:
            add("user_agent_unknown", "warning", "Unrecognized User-Agent platform", "The custom User-Agent does not expose a clear desktop OS token.", "Use a preset User-Agent.")
        same_ua = [
            item for item in (all_profiles or [])
            if item.id != profile.id and item.user_agent and item.user_agent.strip() == profile.user_agent.strip()
        ]
        if same_ua and profile.platform != "windows":
            add("duplicate_user_agent", "warning", "User-Agent reused", f"Also used by: {', '.join(item.name for item in same_ua[:4])}", "Use a different User-Agent preset for this OS.")
        version_match = re.search(r"chrome/(\d+)", ua)
        core_version = str((version_info or {}).get("version") or "")
        core_major = re.search(r"\d+", core_version)
        if version_match and core_major and version_match.group(1) != core_major.group(0):
            add("browser_version", "warning", "Browser version mismatch", f"User-Agent Chrome/{version_match.group(1)} vs core {core_major.group(0)}.", "Use the engine-generated User-Agent.")
        ua_major = chrome_major_from_user_agent(ua)
        if ua_major and int(ua_major) < 120:
            add("old_user_agent", "warning", "Old Chrome User-Agent", f"Chrome/{ua_major} is much older than current web baselines.", "Use a current Chrome User-Agent preset.")

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
            if proxy_record.last_checked_at and is_older_than(proxy_record.last_checked_at, timedelta(hours=2)):
                add(
                    "proxy_stale",
                    "warning",
                    "Proxy result is stale",
                    proxy_record.last_checked_at.replace("T", " "),
                    "Run a fresh proxy check.",
                )
            if profile.auto_geoip and proxy_record.timezone and profile.timezone and profile.timezone != proxy_record.timezone:
                add("timezone_not_synced", "warning", "Stored timezone not synced yet", f"Profile {profile.timezone} / proxy {proxy_record.timezone}", "Recheck the proxy or save the profile again.")
            expected_locale = country_to_locale(proxy_record.country_code)
            if proxy_record.country_code and profile.locale and expected_locale:
                profile_country = _locale_country(profile.locale)
                if profile_country and profile_country != proxy_record.country_code.casefold():
                    add("locale_proxy", "warning", "Locale differs from proxy country", f"Profile {profile.locale} / proxy {proxy_record.country_code.upper()}", f"Use {expected_locale} or enable Based on proxy.")
            proxy_users = [
                item for item in (all_profiles or [])
                if item.id != profile.id and item.proxy and item.proxy == profile.proxy and not item.deleted_at
            ]
            if len(proxy_users) >= 3:
                add("proxy_reuse", "warning", "Proxy reused by many profiles", f"{len(proxy_users) + 1} profiles share this proxy.", "Use Smart Proxy Pool to distribute profiles.")
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


def _locale_country(locale: str) -> str:
    clean = str(locale or "").replace("_", "-").casefold()
    parts = [part for part in clean.split("-") if part]
    return parts[-1] if len(parts) >= 2 and len(parts[-1]) == 2 else ""


def blocker_message(report: CompatibilityReport) -> str:
    lines = ["Fingerprint Compatibility Guard blocked launch:"]
    lines.extend(f"• {issue.title}: {issue.detail}" for issue in report.blockers)
    lines.append("Open profile Settings to fix these items.")
    return "\n".join(lines)
