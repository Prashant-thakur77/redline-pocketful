"""The single error envelope used by every 4xx/5xx response (R-1-060)."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def unauthenticated(message: str = "missing or unknown bearer token") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "not permitted") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "no such resource") -> ApiError:
    return ApiError(404, "not_found", message)


def method_not_allowed(allowed: set[str] | None = None) -> ApiError:
    allowed_str = ", ".join(sorted(allowed)) if allowed else ""
    message = f"method not allowed; try one of: {allowed_str}" if allowed_str else "method not allowed"
    return ApiError(405, "method_not_allowed", message)


def malformed_request(message: str = "request body is not a valid JSON object") -> ApiError:
    return ApiError(400, "malformed_request", message)


def missing_idempotency_key(message: str = "Idempotency-Key header is required") -> ApiError:
    return ApiError(400, "missing_idempotency_key", message)


def idempotency_key_reuse(message: str = "Idempotency-Key was already used with a different request") -> ApiError:
    return ApiError(409, "idempotency_key_reuse", message)


def email_taken(message: str = "email is already registered") -> ApiError:
    return ApiError(409, "email_taken", message)


def handle_taken(message: str = "derived handle is already taken") -> ApiError:
    return ApiError(409, "handle_taken", message)


def validation_failed(message: str = "validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message)


def internal_error(message: str = "unexpected server error") -> ApiError:
    """R-1-080a: a genuine uncaught exception is a server defect, not the
    caller's fault — it must answer loudly, not hide behind a 4xx."""
    return ApiError(500, "internal_error", message)
