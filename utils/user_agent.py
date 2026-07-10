from __future__ import annotations

import random
import re


CHROME_MAJOR_VERSION = "146"


USER_AGENT_PRESETS: dict[str, str] = {
    "windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_MAJOR_VERSION}.0.0.0 Safari/537.36"
    ),
    "macos": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_MAJOR_VERSION}.0.0.0 Safari/537.36"
    ),
    "linux": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_MAJOR_VERSION}.0.0.0 Safari/537.36"
    ),
}


USER_AGENT_POOLS: dict[str, list[str]] = {
    # Chrome intentionally still reports Windows 11 as Windows NT 10.0.
    "windows": [USER_AGENT_PRESETS["windows"]],
    "macos": [
        (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_version}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{CHROME_MAJOR_VERSION}.0.0.0 Safari/537.36"
        )
        for mac_version in ("10_15_7", "11_7_10", "12_7_6", "13_6_7", "14_5_0")
    ],
    "linux": [
        (
            f"Mozilla/5.0 ({linux_token}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{CHROME_MAJOR_VERSION}.0.0.0 Safari/537.36"
        )
        for linux_token in ("X11; Linux x86_64", "X11; Ubuntu; Linux x86_64", "X11; Fedora; Linux x86_64")
    ],
}


USER_AGENT_LABELS = {
    "auto": "Auto - engine generated",
    "windows": "Windows Chrome",
    "macos": "macOS Chrome",
    "linux": "Linux Chrome",
    "custom": "Custom User-Agent",
}


def user_agent_for_mode(mode: str, custom_value: str = "") -> str:
    clean_mode = str(mode or "auto").strip().casefold()
    if clean_mode == "custom":
        return str(custom_value or "").strip()
    return USER_AGENT_PRESETS.get(clean_mode, "")


def user_agent_pool(platform: str) -> list[str]:
    clean_platform = str(platform or "").strip().casefold()
    return list(USER_AGENT_POOLS.get(clean_platform) or USER_AGENT_POOLS["windows"])


def unique_user_agent(platform: str, used: set[str] | None = None) -> str:
    used = used if used is not None else set()
    pool = [item for item in user_agent_pool(platform) if item not in used]
    if not pool:
        pool = user_agent_pool(platform)
    value = random.choice(pool)
    used.add(value)
    return value


def detect_user_agent_mode(user_agent: str) -> str:
    clean = str(user_agent or "").strip()
    if not clean:
        return "auto"
    for mode, preset in USER_AGENT_PRESETS.items():
        if clean == preset:
            return mode
    for mode, pool in USER_AGENT_POOLS.items():
        if clean in pool:
            return mode
    return "custom"


def user_agent_platform(user_agent: str) -> str:
    clean = str(user_agent or "").casefold()
    if "windows nt" in clean:
        return "windows"
    if "macintosh" in clean or "mac os x" in clean:
        return "macos"
    if "x11" in clean or "linux" in clean:
        return "linux"
    return ""


def chrome_major_from_user_agent(user_agent: str) -> str:
    match = re.search(r"chrome/(\d+)", str(user_agent or ""), re.IGNORECASE)
    return match.group(1) if match else ""
