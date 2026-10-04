"""Entrypoint: binds 0.0.0.0:$PORT (default 8080), R-1-012."""
from __future__ import annotations

import os

from service.routes import register_all
from service.server import make_server


def main() -> None:
    port = int(os.environ.get("PORT") or "8080")
    register_all()
    httpd = make_server("0.0.0.0", port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
