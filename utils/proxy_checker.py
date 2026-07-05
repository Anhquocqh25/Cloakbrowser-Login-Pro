from __future__ import annotations

import ipaddress
import socket
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.request import ProxyHandler, Request, build_opener

from utils.proxy_parser import ParsedProxy, parse_proxy
from utils.ip_location import lookup_ip_location


CHECK_HOST = "api.ipify.org"
CHECK_URL = f"http://{CHECK_HOST}/"


@dataclass(frozen=True, slots=True)
class ProxyCheckResult:
    alive: bool
    latency_ms: int = 0
    exit_ip: str = ""
    error: str = ""
    checked_at: str = ""
    location: str = ""
    country_code: str = ""
    timezone: str = ""


def check_proxy(proxy_url: str, timeout: float = 8.0) -> ProxyCheckResult:
    """Verify that a proxy can authenticate and reach the public Internet."""
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.monotonic()
    try:
        parsed = parse_proxy(proxy_url)
        if parsed is None:
            raise ValueError("Proxy is empty.")
        if parsed.scheme == "socks5":
            exit_ip = _check_socks5(parsed, timeout)
        else:
            exit_ip = _check_http(parsed, timeout)
        latency = max(1, round((time.monotonic() - started) * 1000))
        location = lookup_ip_location(exit_ip)
        return ProxyCheckResult(
            True, latency, exit_ip, "", checked_at,
            location.label, location.country_code, location.timezone,
        )
    except Exception as error:
        latency = max(1, round((time.monotonic() - started) * 1000))
        message = str(error).strip() or error.__class__.__name__
        return ProxyCheckResult(False, latency, "", message[:300], checked_at)


def _check_http(proxy: ParsedProxy, timeout: float) -> str:
    opener = build_opener(ProxyHandler({"http": proxy.url, "https": proxy.url}))
    request = Request(CHECK_URL, headers={"User-Agent": "CloakBrowser-ProxyCheck/1.0"})
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"Check endpoint returned HTTP {response.status}.")
        body = response.read(128).decode("ascii", errors="replace").strip()
    return _validated_ip(body)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise OSError("Proxy closed the connection unexpectedly.")
        chunks.extend(chunk)
    return bytes(chunks)


def _check_socks5(proxy: ParsedProxy, timeout: float) -> str:
    with socket.create_connection((proxy.host, proxy.port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        methods = b"\x00\x02" if proxy.username else b"\x00"
        connection.sendall(b"\x05" + bytes([len(methods)]) + methods)
        version, method = _recv_exact(connection, 2)
        if version != 5 or method == 0xFF:
            raise OSError("SOCKS5 proxy rejected authentication methods.")
        if method == 2:
            username = proxy.username.encode("utf-8")
            password = proxy.password.encode("utf-8")
            if not username or len(username) > 255 or len(password) > 255:
                raise OSError("SOCKS5 credentials are invalid or too long.")
            connection.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
            auth_version, auth_status = _recv_exact(connection, 2)
            if auth_version != 1 or auth_status != 0:
                raise OSError("SOCKS5 username or password was rejected.")

        destination = CHECK_HOST.encode("ascii")
        connection.sendall(b"\x05\x01\x00\x03" + bytes([len(destination)]) + destination + struct.pack("!H", 80))
        version, reply, _reserved, address_type = _recv_exact(connection, 4)
        if version != 5 or reply != 0:
            raise OSError(f"SOCKS5 connection failed (code {reply}).")
        if address_type == 1:
            _recv_exact(connection, 4)
        elif address_type == 3:
            _recv_exact(connection, _recv_exact(connection, 1)[0])
        elif address_type == 4:
            _recv_exact(connection, 16)
        else:
            raise OSError("SOCKS5 proxy returned an invalid address type.")
        _recv_exact(connection, 2)

        connection.sendall(
            f"GET / HTTP/1.1\r\nHost: {CHECK_HOST}\r\nUser-Agent: CloakBrowser-ProxyCheck/1.0\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        response = bytearray()
        while len(response) < 16384:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
        header, separator, body = bytes(response).partition(b"\r\n\r\n")
        if not separator or b" 200 " not in header.split(b"\r\n", 1)[0]:
            raise OSError("SOCKS5 proxy could not reach the check endpoint.")
        return _validated_ip(body.decode("ascii", errors="replace").strip())


def _validated_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as error:
        raise OSError("Proxy returned an invalid public IP response.") from error
