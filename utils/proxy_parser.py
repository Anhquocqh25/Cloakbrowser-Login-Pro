from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5"}


@dataclass(frozen=True, slots=True)
class ParsedProxy:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        credentials = ""
        if self.username or self.password:
            credentials = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        return f"{self.scheme}://{credentials}{host}:{self.port}"

    @property
    def masked(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        credentials = f"{self.username}:••••@" if self.username or self.password else ""
        return f"{self.scheme}://{credentials}{host}:{self.port}"


def parse_proxy(value: str | None, default_scheme: str = "http") -> ParsedProxy | None:
    """Parse a proxy URL or host:port[:username:password] shorthand."""
    raw = (value or "").strip()
    if not raw:
        return None

    scheme = default_scheme.lower().strip()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError("Proxy type must be HTTP, HTTPS or SOCKS5.")

    # Parse the four-part shorthand before urlsplit, which would otherwise
    # interpret the extra fields as an invalid port.
    if "://" not in raw and not raw.startswith("["):
        fields = raw.split(":", 3)
        if len(fields) in {2, 4}:
            host = fields[0].strip()
            try:
                port = int(fields[1])
            except ValueError as error:
                raise ValueError("Proxy port must be a number.") from error
            username = fields[2] if len(fields) == 4 else ""
            password = fields[3] if len(fields) == 4 else ""
            return _validated_proxy(scheme, host, port, username, password)
        if len(fields) == 3:
            raise ValueError("Use ip:port or ip:port:username:password.")

    candidate = raw if "://" in raw else f"{scheme}://{raw}"
    try:
        parts = urlsplit(candidate)
        parsed_scheme = parts.scheme.lower()
        if parsed_scheme not in SUPPORTED_PROXY_SCHEMES:
            raise ValueError("Proxy type must be HTTP, HTTPS or SOCKS5.")
        host = parts.hostname or ""
        port = parts.port
    except ValueError as error:
        raise ValueError(f"Invalid proxy: {error}") from error

    return _validated_proxy(
        parsed_scheme,
        host,
        port,
        unquote(parts.username or ""),
        unquote(parts.password or ""),
    )


def normalize_proxy(value: str | None, default_scheme: str = "http") -> str | None:
    parsed = parse_proxy(value, default_scheme)
    return parsed.url if parsed else None


def _validated_proxy(
    scheme: str, host: str, port: int | None, username: str, password: str
) -> ParsedProxy:
    if not host or any(character.isspace() for character in host):
        raise ValueError("Proxy host/IP is invalid.")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Proxy port must be between 1 and 65535.")
    if bool(username) != bool(password):
        raise ValueError("Proxy authentication requires both username and password.")
    return ParsedProxy(scheme, host, port, username, password)
