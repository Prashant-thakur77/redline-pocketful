"""Adversarial findings against N1-1 (runtime skeleton / routing / error envelope).

Both tests fail against commit 7fca98b.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import BASE_URL  # noqa: E402


def test_head_method_is_not_a_5xx_r_1_005():
    """R-1-005: no request produces a 5xx response.

    `Handler` only defines do_GET/do_POST/do_PUT/do_PATCH/do_DELETE, so an
    HTTP/1.1-legal HEAD request falls through to BaseHTTPRequestHandler's
    default, which answers 501 Unsupported method with an HTML body —
    both the status (5xx) and the envelope (R-1-060) are wrong.
    """
    resp = httpx.request("HEAD", BASE_URL + "/health", timeout=10.0)
    assert resp.status_code < 500, (
        f"HEAD /health returned a 5xx ({resp.status_code}): {resp.text!r}"
    )


def test_options_method_is_not_a_5xx_r_1_005():
    """Same bug as above, via OPTIONS instead of HEAD."""
    resp = httpx.request("OPTIONS", BASE_URL + "/health", timeout=10.0)
    assert resp.status_code < 500, (
        f"OPTIONS /health returned a 5xx ({resp.status_code}): {resp.text!r}"
    )


def test_malformed_content_length_gets_a_response_not_a_dropped_connection():
    """R-1-005 / R-1-060: a request must be answered, and any 4xx/5xx body
    must be the error envelope — never an unhandled exception.

    `server.py`'s `_dispatch` does
    `int(self.headers.get("Content-Length", 0) or 0)` *before* the
    try/except that wraps endpoint handling. A non-numeric Content-Length
    header raises an uncaught ValueError, which the stdlib's
    ThreadingHTTPServer answers by closing the socket with no HTTP
    response at all — worse than the 500 the pipeline otherwise converts
    every unexpected exception into.
    """
    parts = urlsplit(BASE_URL)
    host, port = parts.hostname, parts.port or 80
    with socket.create_connection((host, port), timeout=5.0) as s:
        s.sendall(
            b"POST /health HTTP/1.1\r\n"
            b"Host: x\r\n"
            b"Content-Length: abc\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        s.settimeout(5.0)
        data = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
    assert data.startswith(b"HTTP/1."), (
        f"request with a malformed Content-Length header got no HTTP response at all: {data!r}"
    )
    status_line = data.split(b"\r\n", 1)[0]
    status_code = int(status_line.split(b" ")[1])
    assert status_code < 500, f"expected a 4xx error envelope, got {status_line!r}"
