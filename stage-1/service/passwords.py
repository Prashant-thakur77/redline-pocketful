"""Password hashing (R-1-091): PBKDF2-HMAC-SHA256, stdlib only — no
outbound network and no third-party package needed at build or run time."""
from __future__ import annotations

import hashlib
import hmac
import os

_ALGO = "sha256"
_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2${_ALGO}${_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, algo, iterations, salt_hex, hash_hex = stored_hash.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    derived = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(derived, expected)
