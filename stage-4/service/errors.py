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


def self_payment(message: str = "cannot pay yourself") -> ApiError:
    return ApiError(422, "self_payment", message)


def self_request(message: str = "cannot request money from yourself") -> ApiError:
    return ApiError(422, "self_request", message)


def insufficient_funds(message: str = "insufficient funds") -> ApiError:
    return ApiError(409, "insufficient_funds", message)


def request_not_pending(message: str = "request is not pending") -> ApiError:
    return ApiError(409, "request_not_pending", message)


def authorization_expired(message: str = "authorization has expired") -> ApiError:
    return ApiError(409, "authorization_expired", message)


def authorization_not_open(message: str = "authorization is not open") -> ApiError:
    return ApiError(409, "authorization_not_open", message)


def capture_exceeds_authorization(message: str = "capture amount exceeds the remaining authorized amount") -> ApiError:
    return ApiError(422, "capture_exceeds_authorization", message)


def stale_revision(message: str = "expected_revision does not match the payment's current revision") -> ApiError:
    return ApiError(409, "stale_revision", message)


def linked_payment_immutable(message: str = "a settlement- or capture-produced payment cannot be corrected") -> ApiError:
    return ApiError(422, "linked_payment_immutable", message)


def historical_overdraft(message: str = "correction would make a balance negative at some effective instant") -> ApiError:
    return ApiError(409, "historical_overdraft", message)


def incomplete_settlement(message: str = "a correction batch must include every member of any settlement it touches") -> ApiError:
    return ApiError(422, "incomplete_settlement", message)


def invalid_refund_target(message: str = "a refund cannot itself be refunded") -> ApiError:
    return ApiError(422, "invalid_refund_target", message)


def refund_exceeds_payment(message: str = "refund amount exceeds the payment's refundable balance") -> ApiError:
    return ApiError(422, "refund_exceeds_payment", message)


def internal_error(message: str = "unexpected server error") -> ApiError:
    """R-1-080a: a genuine uncaught exception is a server defect, not the
    caller's fault — it must answer loudly, not hide behind a 4xx."""
    return ApiError(500, "internal_error", message)
