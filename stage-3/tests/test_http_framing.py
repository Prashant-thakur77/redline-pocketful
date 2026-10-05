"""HTTP framing and routing edge cases not owned by @adversary: R-1-079.

@adversary's folder already covers HEAD-on-a-GET-able-path, OPTIONS -> 204,
and 405-on-wrong-method. This file covers what is left: an over-long request
line, an over-long header block, the exact contents of the Allow header, and
HEAD on an unrouted (404) path.
"""
from __future__ import annotations

import json
import socket
import urllib.parse

import httpx

from conftest import BASE_URL, url


def _send_raw(request_bytes: bytes, timeout: float = 5.0) -> bytes:
    """Read the full response: the header block, then exactly the body
    `Content-Length` declares.

    The previous version stopped as soon as it saw `\\r\\n\\r\\n` anywhere in
    the accumulated bytes — i.e. the instant the header block was complete —
    without reading the declared body length. That is only safe when a
    single `recv()` happens to return the whole response in one segment; it
    truncates the body whenever the body arrives in a later TCP read than
    the headers (an everyday occurrence across a real network, and the
    reason it was indistinguishable from correct against an in-process test
    server that coalesces its writes into one segment). This nearly closed
    stage 1 over a live R-1-060/R-1-079 breach that this exact test suite
    could not see because of it.
    """
    parsed = urllib.parse.urlsplit(BASE_URL)
    host, port = parsed.hostname, parsed.port or 80
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(request_bytes)
        sock.settimeout(timeout)
        buf = b""
        header_end = -1
        try:
            while header_end == -1:
                chunk = sock.recv(8192)
                if not chunk:
                    return buf  # connection closed before the headers completed
                buf += chunk
                header_end = buf.find(b"\r\n\r\n")
        except socket.timeout:
            return buf

        content_length = None
        for line in buf[:header_end].split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                content_length = int(value.strip())
                break

        if content_length is None:
            # no declared length: read until the connection closes.
            try:
                while True:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    buf += chunk
            except socket.timeout:
                pass
            return buf

        needed = header_end + 4 + content_length
        try:
            while len(buf) < needed:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        return buf


def _status_code(raw: bytes) -> int:
    assert raw, "no response received at all"
    status_line = raw.split(b"\r\n", 1)[0]
    parts = status_line.split(b" ")
    assert len(parts) >= 2, f"not a valid HTTP status line: {status_line!r}"
    return int(parts[1])


def _error_body(raw: bytes) -> dict:
    """Parse the JSON error envelope out of a raw socket response. These
    framing-error paths are the ones most likely to rely on a generic
    fallback message, so — unlike every assert_error()-based test elsewhere
    in this suite — they are worth checking the body of, not just the
    status line."""
    assert b"\r\n\r\n" in raw, f"no header/body separator found: {raw[:200]!r}"
    _, _, body = raw.partition(b"\r\n\r\n")
    return json.loads(body.decode("utf-8"))


def test_over_long_request_line_400():
    """R-1-079, R-1-060: an over-long request line is a client-caused
    framing error, never a dropped connection and never a framework's own
    error page — and the envelope's message must be a non-empty string like
    every other error response."""
    long_path = "/" + ("a" * 100_000)
    request = f"GET {long_path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode()
    raw = _send_raw(request)
    assert _status_code(raw) == 400
    assert b"<html" not in raw.lower(), "no HTML error page may ever be emitted"
    body = _error_body(raw)
    assert body["error"]["code"] == "malformed_request"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def test_over_long_header_block_400():
    """R-1-079, R-1-060: an over-long header block is a client-caused
    framing error, with the same non-empty-message requirement."""
    padding = "".join(f"X-Pad-{i}: {'a' * 1000}\r\n" for i in range(200))
    request = f"GET /health HTTP/1.1\r\nHost: test\r\n{padding}Connection: close\r\n\r\n".encode()
    raw = _send_raw(request)
    assert _status_code(raw) == 400
    assert b"<html" not in raw.lower()
    body = _error_body(raw)
    assert body["error"]["code"] == "malformed_request"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


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
    """R-1-079, R-1-060: HEAD on a path with no route at all answers with
    the same status GET would give (404) and no body; GET's own body (which
    HEAD, by definition, has none of to check) must carry a non-empty
    message like every other error response."""
    unrouted = "/totally-unrouted-resource-xyz"
    get_resp = httpx.get(url(unrouted))
    head_resp = httpx.request("HEAD", url(unrouted))
    assert get_resp.status_code == 404
    assert isinstance(get_resp.json()["error"]["message"], str) and get_resp.json()["error"]["message"]
    assert head_resp.status_code == 404
    assert head_resp.content == b""
