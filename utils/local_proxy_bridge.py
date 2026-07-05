from __future__ import annotations

import base64
import select
import socket
import socketserver
import ssl
import struct
import threading
from urllib.parse import urlsplit

from utils.proxy_parser import ParsedProxy, parse_proxy


def _read_until(connection: socket.socket, marker: bytes, limit: int = 65536) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = connection.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise OSError("Proxy request headers are too large.")
    return bytes(data)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise OSError("Upstream proxy closed the connection.")
        data.extend(chunk)
    return bytes(data)


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    while sockets:
        readable, _, exceptional = select.select(sockets, [], sockets, 1.0)
        if exceptional:
            return
        for source in readable:
            try:
                payload = source.recv(65536)
            except OSError:
                return
            if not payload:
                return
            destination = right if source is left else left
            try:
                destination.sendall(payload)
            except OSError:
                return


def _target_from_request(method: str, target: str, headers: list[str]) -> tuple[str, int]:
    if method == "CONNECT":
        host, separator, port = target.rpartition(":")
        return (host.strip("[]"), int(port)) if separator else (target, 443)
    parsed = urlsplit(target)
    if parsed.hostname:
        return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    host_header = next((line for line in headers if line.lower().startswith("host:")), "")
    value = host_header.split(":", 1)[1].strip() if ":" in host_header else ""
    host, separator, port = value.rpartition(":")
    return (host.strip("[]"), int(port)) if separator and port.isdigit() else (value, 80)


def _connect_upstream(upstream: ParsedProxy, timeout: float = 12.0) -> socket.socket:
    connection = socket.create_connection((upstream.host, upstream.port), timeout=timeout)
    connection.settimeout(timeout)
    if upstream.scheme == "https":
        connection = ssl.create_default_context().wrap_socket(
            connection, server_hostname=upstream.host
        )
    return connection


def _socks_connect(upstream: ParsedProxy, host: str, port: int) -> socket.socket:
    connection = _connect_upstream(upstream)
    methods = b"\x00\x02" if upstream.username else b"\x00"
    connection.sendall(b"\x05" + bytes([len(methods)]) + methods)
    version, method = _recv_exact(connection, 2)
    if version != 5 or method == 0xFF:
        raise OSError("SOCKS5 proxy rejected authentication methods.")
    if method == 2:
        username = upstream.username.encode("utf-8")
        password = upstream.password.encode("utf-8")
        connection.sendall(
            b"\x01" + bytes([len(username)]) + username
            + bytes([len(password)]) + password
        )
        if _recv_exact(connection, 2) != b"\x01\x00":
            raise OSError("SOCKS5 username or password was rejected.")
    encoded_host = host.encode("idna")
    connection.sendall(
        b"\x05\x01\x00\x03" + bytes([len(encoded_host)])
        + encoded_host + struct.pack("!H", port)
    )
    version, reply, _reserved, address_type = _recv_exact(connection, 4)
    if version != 5 or reply != 0:
        raise OSError(f"SOCKS5 connection failed (code {reply}).")
    if address_type == 1:
        _recv_exact(connection, 4)
    elif address_type == 3:
        _recv_exact(connection, _recv_exact(connection, 1)[0])
    elif address_type == 4:
        _recv_exact(connection, 16)
    _recv_exact(connection, 2)
    return connection


class _BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client: socket.socket = self.request
        client.settimeout(15.0)
        upstream_connection: socket.socket | None = None
        try:
            request = _read_until(client, b"\r\n\r\n")
            header, separator, remainder = request.partition(b"\r\n\r\n")
            if not separator:
                raise OSError("Invalid HTTP proxy request.")
            lines = header.decode("iso-8859-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            host, port = _target_from_request(method.upper(), target, lines[1:])
            upstream: ParsedProxy = self.server.upstream  # type: ignore[attr-defined]

            if upstream.scheme == "socks5":
                upstream_connection = _socks_connect(upstream, host, port)
                if method.upper() == "CONNECT":
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                else:
                    parsed = urlsplit(target)
                    origin_target = parsed.path or "/"
                    if parsed.query:
                        origin_target += "?" + parsed.query
                    forwarded = [f"{method} {origin_target} {version}"] + [
                        line for line in lines[1:]
                        if not line.lower().startswith(("proxy-authorization:", "proxy-connection:"))
                    ]
                    upstream_connection.sendall(
                        ("\r\n".join(forwarded) + "\r\n\r\n").encode("iso-8859-1") + remainder
                    )
            else:
                upstream_connection = _connect_upstream(upstream)
                authorization = ""
                if upstream.username:
                    token = base64.b64encode(
                        f"{upstream.username}:{upstream.password}".encode("utf-8")
                    ).decode("ascii")
                    authorization = f"Proxy-Authorization: Basic {token}"
                forwarded = [lines[0]] + [
                    line for line in lines[1:]
                    if not line.lower().startswith(("proxy-authorization:", "proxy-connection:"))
                ]
                if authorization:
                    forwarded.append(authorization)
                upstream_connection.sendall(
                    ("\r\n".join(forwarded) + "\r\n\r\n").encode("iso-8859-1") + remainder
                )
                if method.upper() == "CONNECT":
                    response = _read_until(upstream_connection, b"\r\n\r\n")
                    first_line = response.split(b"\r\n", 1)[0]
                    if b" 200 " not in first_line:
                        client.sendall(response)
                        return
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

            _relay(client, upstream_connection)
        except Exception as error:
            try:
                message = str(error).replace("\r", " ").replace("\n", " ")[:180]
                client.sendall(
                    "HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n"
                    f"Content-Length: {len(message.encode('utf-8'))}\r\n\r\n{message}".encode("utf-8")
                )
            except OSError:
                pass
        finally:
            if upstream_connection is not None:
                try:
                    upstream_connection.close()
                except OSError:
                    pass


class _BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, upstream: ParsedProxy) -> None:
        self.upstream = upstream
        super().__init__(("127.0.0.1", 0), _BridgeHandler)


class LocalProxyBridge:
    def __init__(self, proxy_url: str) -> None:
        parsed = parse_proxy(proxy_url)
        if parsed is None:
            raise ValueError("Proxy is required for the local bridge.")
        self.server = _BridgeServer(parsed)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="CloakLocalProxyBridge",
            daemon=True,
        )

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "LocalProxyBridge":
        self.thread.start()
        return self

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
