from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtWidgets import QComboBox

from config import DEFAULT_LOCALE, DEFAULT_TIMEZONE


COMMON_TIMEZONES = (
    "Pacific/Honolulu",
    "America/Anchorage",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Toronto",
    "America/Sao_Paulo",
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Amsterdam",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Warsaw",
    "Europe/Kyiv",
    "Europe/Moscow",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Ho_Chi_Minh",
    "Asia/Jakarta",
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Seoul",
    "Asia/Tokyo",
    "Australia/Perth",
    "Australia/Sydney",
    "Pacific/Auckland",
)


FALLBACK_OFFSETS = {
    "Pacific/Honolulu": -10 * 60,
    "America/Anchorage": -9 * 60,
    "America/Los_Angeles": -8 * 60,
    "America/Denver": -7 * 60,
    "America/Chicago": -6 * 60,
    "America/New_York": -5 * 60,
    "America/Toronto": -5 * 60,
    "America/Sao_Paulo": -3 * 60,
    "UTC": 0,
    "Europe/London": 0,
    "Europe/Paris": 60,
    "Europe/Berlin": 60,
    "Europe/Amsterdam": 60,
    "Europe/Madrid": 60,
    "Europe/Rome": 60,
    "Europe/Warsaw": 60,
    "Europe/Kyiv": 120,
    "Europe/Moscow": 180,
    "Africa/Cairo": 120,
    "Africa/Johannesburg": 120,
    "Asia/Dubai": 240,
    "Asia/Karachi": 300,
    "Asia/Kolkata": 330,
    "Asia/Dhaka": 360,
    "Asia/Bangkok": 420,
    "Asia/Ho_Chi_Minh": 420,
    "Asia/Jakarta": 420,
    "Asia/Singapore": 480,
    "Asia/Shanghai": 480,
    "Asia/Hong_Kong": 480,
    "Asia/Taipei": 480,
    "Asia/Seoul": 540,
    "Asia/Tokyo": 540,
    "Australia/Perth": 480,
    "Australia/Sydney": 600,
    "Pacific/Auckland": 720,
}


COMMON_LOCALES = (
    ("en-US", "English (United States)"),
    ("en-GB", "English (United Kingdom)"),
    ("vi-VN", "Tiếng Việt (Việt Nam)"),
    ("th-TH", "Thai (Thailand)"),
    ("id-ID", "Indonesian (Indonesia)"),
    ("ms-MY", "Malay (Malaysia)"),
    ("fil-PH", "Filipino (Philippines)"),
    ("zh-CN", "Chinese (China)"),
    ("zh-HK", "Chinese (Hong Kong)"),
    ("zh-TW", "Chinese (Taiwan)"),
    ("ja-JP", "Japanese (Japan)"),
    ("ko-KR", "Korean (Korea)"),
    ("fr-FR", "French (France)"),
    ("de-DE", "German (Germany)"),
    ("es-ES", "Spanish (Spain)"),
    ("it-IT", "Italian (Italy)"),
    ("nl-NL", "Dutch (Netherlands)"),
    ("pl-PL", "Polish (Poland)"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("ru-RU", "Russian (Russia)"),
    ("tr-TR", "Turkish (Turkey)"),
    ("ar-SA", "Arabic (Saudi Arabia)"),
    ("hi-IN", "Hindi (India)"),
)


COUNTRY_LOCALE = {
    "US": "en-US",
    "GB": "en-GB",
    "VN": "vi-VN",
    "TH": "th-TH",
    "ID": "id-ID",
    "MY": "ms-MY",
    "PH": "fil-PH",
    "CN": "zh-CN",
    "HK": "zh-HK",
    "TW": "zh-TW",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "FR": "fr-FR",
    "DE": "de-DE",
    "ES": "es-ES",
    "IT": "it-IT",
    "NL": "nl-NL",
    "PL": "pl-PL",
    "BR": "pt-BR",
    "RU": "ru-RU",
    "TR": "tr-TR",
    "SA": "ar-SA",
    "IN": "hi-IN",
    "CA": "en-US",
    "AU": "en-GB",
    "SG": "en-GB",
}


def _offset_minutes(timezone_id: str) -> int | None:
    try:
        now = datetime.now(ZoneInfo(timezone_id))
        offset = now.utcoffset()
        if offset is not None:
            return int(offset.total_seconds() // 60)
    except Exception:
        pass
    return FALLBACK_OFFSETS.get(timezone_id)


def _format_offset(minutes: int | None) -> str:
    if minutes is None:
        return "UTC"
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    hours, mins = divmod(absolute, 60)
    return f"UTC {sign}{hours:02d}:{mins:02d}"


def timezone_label(timezone_id: str) -> str:
    timezone_id = str(timezone_id or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    return f"{_format_offset(_offset_minutes(timezone_id))} · {timezone_id}"


def locale_label(locale: str) -> str:
    locale = str(locale or DEFAULT_LOCALE).strip() or DEFAULT_LOCALE
    names = {code: name for code, name in COMMON_LOCALES}
    return f"{locale} · {names.get(locale, 'Custom locale')}"


def country_to_locale(country_code: str) -> str:
    return COUNTRY_LOCALE.get(str(country_code or "").upper(), "")


def populate_timezone_combo(combo: QComboBox, current: str = DEFAULT_TIMEZONE) -> None:
    combo.clear()
    seen: set[str] = set()
    for timezone_id in COMMON_TIMEZONES:
        if timezone_id in seen:
            continue
        seen.add(timezone_id)
        combo.addItem(timezone_label(timezone_id), timezone_id)
    combo.setMaxVisibleItems(14)
    set_combo_value(combo, current or DEFAULT_TIMEZONE, timezone_label)


def populate_locale_combo(combo: QComboBox, current: str = DEFAULT_LOCALE) -> None:
    combo.clear()
    for locale, name in COMMON_LOCALES:
        combo.addItem(f"{locale} · {name}", locale)
    combo.setMaxVisibleItems(14)
    set_combo_value(combo, current or DEFAULT_LOCALE, locale_label)


def set_combo_value(combo: QComboBox, value: str, label_builder=timezone_label) -> None:
    value = str(value or "").strip()
    if not value:
        return
    index = combo.findData(value)
    if index < 0:
        combo.addItem(label_builder(value), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)


def combo_value(combo: QComboBox, fallback: str) -> str:
    data = combo.currentData()
    if isinstance(data, str) and data.strip():
        return data.strip()
    text = combo.currentText().strip()
    if "·" in text:
        text = text.split("·", 1)[1].strip()
    return text or fallback
