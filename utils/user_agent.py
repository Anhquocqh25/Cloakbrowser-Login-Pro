from __future__ import annotations

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


def detect_user_agent_mode(user_agent: str) -> str:
    clean = str(user_agent or "").strip()
    if not clean:
        return "auto"
    for mode, preset in USER_AGENT_PRESETS.items():
        if clean == preset:
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
