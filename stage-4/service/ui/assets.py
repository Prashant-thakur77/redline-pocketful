"""Static runtime assets, loaded once from disk at import time and served
byte-for-byte from the image (R-2-092: no CDN, no external font, no
outbound request of any kind)."""
from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"

CONTENT_TYPES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}

FILES: dict[str, bytes] = {
    name: (_STATIC_DIR / name).read_bytes() for name in CONTENT_TYPES
}
