"""HTTP routing and dispatch (R-1-012, R-1-013, R-1-020, R-1-060).

Stdlib only, so the image needs no build-time package fetch and the
container makes no outbound request at run time. A threaded server is
enough for 50 in-flight requests when every handler is fast in-memory work
guarded by one lock (see store.py / pipeline.py).
"""
from __future__ import annotations

import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from .errors import ApiError, malformed_request, not_found
from .json_utils import dumps
from .pipeline import Endpoint, RequestCtx

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class Router:
    def __init__(self):
        self._routes: list[tuple[str, re.Pattern, Endpoint]] = []

    def add(self, method: str, path_pattern: str, endpoint: Endpoint) -> None:
        regex = _PARAM_RE.sub(r"(?P<\1>[^/]+)", path_pattern)
        self._routes.append((method.upper(), re.compile(f"^{regex}$"), endpoint))

    def match(self, method: str, path: str):
        for route_method, regex, endpoint in self._routes:
            if route_method != method.upper():
                continue
            m = regex.match(path)
            if m:
                return endpoint, m.groupdict()
        return None, None


ROUTER = Router()


class Handler(BaseHTTPRequestHandler):
    server_version = "pocketful/1.0"
    protocol_version = "HTTP/1.1"

    def _dispatch(self, method: str, suppress_body: bool = False) -> None:
        try:
            split = urlsplit(self.path)
            path = split.path
            query = {k: v for k, v in parse_qsl(split.query, keep_blank_values=True)}

            raw_length = self.headers.get("Content-Length")
            length = 0
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError:
                    raise malformed_request("Content-Length must be a valid integer")
            raw_body = self.rfile.read(length) if length > 0 else b""

            headers = {k.lower(): v for k, v in self.headers.items()}

            endpoint, path_params = ROUTER.match(method, path)
            if endpoint is None:
                raise not_found(f"no such endpoint: {method} {path}")

            ctx = RequestCtx(method=method, path=path, raw_body=raw_body, headers=headers,
                             query=query, path_params=path_params or {})
            status, body = endpoint.handle(ctx)
        except ApiError as exc:
            self._write_error(exc, suppress_body=suppress_body)
            return
        except Exception:
            traceback.print_exc()
            self._write_error(ApiError(500, "internal_error", "unexpected server error"), suppress_body=suppress_body)
            return
        self._write_json(status, body, suppress_body=suppress_body)

    def _write_json(self, status: int, body: dict | None, suppress_body: bool = False) -> None:
        if body is None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = dumps(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not suppress_body:
            self.wfile.write(payload)

    def _write_error(self, exc: ApiError, suppress_body: bool = False) -> None:
        self._write_json(exc.status, exc.body(), suppress_body=suppress_body)

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET", suppress_body=True)

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, fmt, *args):
        pass  # keep container logs quiet; stdout/stderr still available via traceback.print_exc


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)
