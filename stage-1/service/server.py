"""HTTP routing and dispatch (R-1-012, R-1-013, R-1-020, R-1-060, R-1-079).

Stdlib only, so the image needs no build-time package fetch and the
container makes no outbound request at run time. A threaded server is
enough for 50 in-flight requests when every handler is fast in-memory work
guarded by one lock (see store.py / pipeline.py).

R-1-079 is an invariant on the whole transport, not an endpoint behaviour:
every client-caused condition `BaseHTTPRequestHandler` would otherwise
answer with its own HTML error page (unsupported method, bad request
line, headers/URI too long, unsupported HTTP version) is intercepted via
`send_error` and turned into the same JSON envelope every endpoint uses,
mapped to the correct 4xx. A condition that is NOT one of those — a
genuine defect in our own code — answers 500 internal_error through the
same envelope instead: R-1-080a, loud and honest, never relabelled as a
4xx to make a gate look green.
"""
from __future__ import annotations

import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from .errors import ApiError, internal_error, malformed_request, method_not_allowed, not_found
from .json_utils import dumps
from .pipeline import Endpoint, RequestCtx

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MiB; well over any real request body here

# Maps a status code BaseHTTPRequestHandler's internals might pass to
# send_error (bad request line, headers/URI too long, unsupported method,
# unsupported HTTP version) to the (status, code) our envelope actually
# emits — never the stdlib default, and never a 5xx (R-1-079).
_STDLIB_ERROR_MAP: dict[int, tuple[int, str]] = {
    400: (400, "malformed_request"),
    404: (404, "not_found"),
    405: (405, "method_not_allowed"),
    414: (400, "malformed_request"),   # URI too long
    431: (400, "malformed_request"),   # header fields too large
    501: (405, "method_not_allowed"),  # "Unsupported method" from handle_one_request
    505: (400, "malformed_request"),   # HTTP version not supported
}


def _map_stdlib_error(code: int) -> tuple[int, str]:
    """Only the client-caused conditions named in R-1-079 get remapped to a
    4xx envelope. Anything else the stdlib hands us (an internal failure
    inside its own request handling, not one of the named framing errors)
    is a server defect — R-1-080a says that answers 500 internal_error,
    loudly, not a 4xx that hides it from the gates."""
    if code in _STDLIB_ERROR_MAP:
        return _STDLIB_ERROR_MAP[code]
    if code >= 500:
        return 500, "internal_error"
    if code >= 400:
        return code, "malformed_request"
    return 400, "malformed_request"


class Router:
    def __init__(self):
        self._routes: list[tuple[str, re.Pattern, Endpoint]] = []

    def add(self, method: str, path_pattern: str, endpoint: Endpoint) -> None:
        regex = _PARAM_RE.sub(r"(?P<\1>[^/]+)", path_pattern)
        self._routes.append((method.upper(), re.compile(f"^{regex}$"), endpoint))

    def match(self, method: str, path: str):
        """Return (endpoint, path_params, allowed_methods).

        `endpoint` is None and `allowed_methods` non-empty when the path
        exists but not for this method (-> 405); both are empty/None when
        no route matches the path at all (-> 404)."""
        allowed: set[str] = set()
        for route_method, regex, endpoint in self._routes:
            m = regex.match(path)
            if not m:
                continue
            allowed.add(route_method)
            if route_method == method.upper():
                return endpoint, m.groupdict(), allowed
        return None, None, allowed

    def allowed_methods(self, path: str) -> set[str]:
        return {route_method for route_method, regex, _ in self._routes if regex.match(path)}


ROUTER = Router()


class Handler(BaseHTTPRequestHandler):
    server_version = "pocketful/1.0"
    protocol_version = "HTTP/1.1"

    # --- the R-1-079 safety net: no stdlib HTML error page ever reaches the wire ---
    def send_error(self, code, message=None, explain=None):
        status, error_code = _map_stdlib_error(int(code))
        body = {"error": {"code": error_code, "message": str(message) if message else error_code.replace("_", " ")}}
        try:
            payload = dumps(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if getattr(self, "command", None) != "HEAD":
                self.wfile.write(payload)
        except Exception:
            pass

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
                if length < 0 or length > _MAX_CONTENT_LENGTH:
                    raise malformed_request("Content-Length out of range")
            raw_body = self.rfile.read(length) if length > 0 else b""

            headers = {k.lower(): v for k, v in self.headers.items()}

            endpoint, path_params, allowed = ROUTER.match(method, path)
            if endpoint is None:
                if allowed:
                    raise method_not_allowed(allowed)
                raise not_found(f"no such endpoint: {method} {path}")

            ctx = RequestCtx(method=method, path=path, raw_body=raw_body, headers=headers,
                             query=query, path_params=path_params or {})
            status, body = endpoint.handle(ctx)
        except ApiError as exc:
            self._write_error(exc, suppress_body=suppress_body)
            return
        except Exception:
            traceback.print_exc()
            # R-1-080a: a genuine uncaught exception is a server defect and
            # must say so loudly (500), never be relabelled as the
            # caller's fault — R-1-005 is satisfied by never reaching this
            # path, not by renaming what happens when it is.
            self._write_error(internal_error(), suppress_body=suppress_body)
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
        try:
            path = urlsplit(self.path).path
            allowed = ROUTER.allowed_methods(path)
            if not allowed:
                self._write_error(not_found(f"no such endpoint: OPTIONS {path}"))
                return
            self.send_response(204)
            self.send_header("Allow", ", ".join(sorted(allowed | {"OPTIONS"})))
            self.send_header("Content-Length", "0")
            self.end_headers()
        except Exception:
            traceback.print_exc()
            self._write_error(internal_error())

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


class Server(ThreadingHTTPServer):
    # R-1-005/R-1-015: stdlib's listen() backlog defaults to 5, so with 50
    # requests genuinely in flight the OS itself starts resetting new
    # connections before they ever reach the application — a dropped
    # connection no amount of application-level error handling can catch.
    # Comfortably over the required 50 concurrent, with headroom for the
    # hardening storm's higher counts.
    request_queue_size = 256
    daemon_threads = True
    allow_reuse_address = True


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return Server((host, port), Handler)
