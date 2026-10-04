"""HTTP framing and routing edge cases not owned by @adversary: R-1-079.

@adversary's folder already covers HEAD-on-a-GET-able-path, OPTIONS -> 204,
and 405-on-wrong-method. This file covers what is left: an over-long request
line, an over-long header block, the exact contents of the Allow header, and
HEAD on an unrouted (404) path.
"""
from __future__ import annotations

import socket
import urllib.parse

import httpx

from conftest import BASE_URL, url


def _send_raw(request_bytes: bytes, timeout: float = 5.0) -> bytes:
    parsed = urllib.parse.urlsplit(BASE_URL)
    host, port = parsed.hostname, parsed.port or 80
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(request_bytes)
        sock.settimeout(timeout)
        chunks = []
        try:
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\r\n\r\n" in b"".join(chunks):
                    break
        except socket.timeout:
            pass
        return b"".join(chunks)


def _status_code(raw: bytes) -> int:
    assert raw, "no response received at all"
    status_line = raw.split(b"\r\n", 1)[0]
    parts = status_line.split(b" ")
    assert len(parts) >= 2, f"not a valid HTTP status line: {status_line!r}"
    return int(parts[1])


def test_over_long_request_line_400():
    """R-1-079: an over-long request line is a client-caused framing error,
    never a dropped connection and never a framework's own error page."""
    long_path = "/" + ("a" * 100_000)
    request = f"GET {long_path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode()
    raw = _send_raw(request)
    assert _status_code(raw) == 400
    assert b"<html" not in raw.lower(), "no HTML error page may ever be emitted"


def test_over_long_header_block_400():
    """R-1-079: an over-long header block is a client-caused framing error."""
    padding = "".join(f"X-Pad-{i}: {'a' * 1000}\r\n" for i in range(200))
    request = f"GET /health HTTP/1.1\r\nHost: test\r\n{padding}Connection: close\r\n\r\n".encode()
    raw = _send_raw(request)
    assert _status_code(raw) == 400
    assert b"<html" not in raw.lower()


def test_options_allow_header_lists_actual_methods():
    """R-1-079: the Allow header on OPTIONS names the methods actually routed
    on that path — not just any nonempty value."""
    read_only = httpx.request("OPTIONS", url("/me"))
    assert read_only.status_code == 204
    allow_read_only = {m.strip().upper() for m in read_only.headers.get("allow", "").split(",") if m.strip()}
    assert "GET" in allow_read_only
    assert "POST" not in allow_read_only

    write_only = httpx.request("OPTIONS", url("/payments"))
    assert write_only.status_code == 204
    allow_write_only = {m.strip().upper() for m in write_only.headers.get("allow", "").split(",") if m.strip()}
    assert "POST" in allow_write_only
    assert "GET" not in allow_write_only


def test_head_on_unrouted_path_404_no_body():
    """R-1-079: HEAD on a path with no route at all answers with the same
    status GET would give (404) and no body."""
    unrouted = "/totally-unrouted-resource-xyz"
    get_resp = httpx.get(url(unrouted))
    head_resp = httpx.request("HEAD", url(unrouted))
    assert get_resp.status_code == 404
    assert head_resp.status_code == 404
    assert head_resp.content == b""
