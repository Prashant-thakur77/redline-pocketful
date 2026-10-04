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


def malformed_request(message: str = "request body is not a valid JSON object") -> ApiError:
    return ApiError(400, "malformed_request", message)


def missing_idempotency_key(message: str = "Idempotency-Key header is required") -> ApiError:
    return ApiError(400, "missing_idempotency_key", message)


def idempotency_key_reuse(message: str = "Idempotency-Key was already used with a different request") -> ApiError:
    return ApiError(409, "idempotency_key_reuse", message)


def validation_failed(message: str = "validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message)
