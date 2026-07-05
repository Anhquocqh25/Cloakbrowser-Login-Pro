from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import ipaddress
import threading


_geoip_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class IpLocation:
    label: str = ""
    country_code: str = ""
    country: str = ""
    region: str = ""
    city: str = ""
    timezone: str = ""


def country_code_from_flag_text(value: str) -> str:
    text = str(value or "")
    if len(text) < 2:
        return ""
    first = ord(text[0]) - 0x1F1E6
    second = ord(text[1]) - 0x1F1E6
    if not (0 <= first < 26 and 0 <= second < 26):
        return ""
    return chr(ord("A") + first) + chr(ord("A") + second)


def strip_flag_prefix(value: str) -> str:
    text = str(value or "")
    return text[2:].strip() if country_code_from_flag_text(text) else text.strip()


@lru_cache(maxsize=512)
def lookup_ip_location(ip: str) -> IpLocation:
    """Resolve an exit IP locally with CloakBrowser's signed GeoLite cache.

    Location lookup failure never changes proxy connectivity status; callers
    can safely keep an existing manually entered location.
    """
    ipaddress.ip_address(ip)
    try:
        import geoip2.database
        from cloakbrowser.geoip import _ensure_geoip_db
    except ImportError:
        return IpLocation()

    with _geoip_lock:
        database_path = _ensure_geoip_db()
    if not database_path:
        return IpLocation()

    try:
        with geoip2.database.Reader(str(database_path)) as reader:
            response = reader.city(ip)
            country_code = str(response.country.iso_code or "").upper()
            country = str(response.country.name or "")
            region = str(response.subdivisions.most_specific.name or "")
            city = str(response.city.name or "")
            timezone = str(response.location.time_zone or "")
    except Exception:
        return IpLocation()

    parts: list[str] = []
    for value in (city, region, country):
        if value and value.casefold() not in {item.casefold() for item in parts}:
            parts.append(value)
    label = ", ".join(parts)
    if not label:
        label = country_code
    return IpLocation(label, country_code, country, region, city, timezone)
