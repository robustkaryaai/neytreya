"""
`rmp.error` payload shape (RMP-SPEC §3.2).

There is no separate "error envelope shape" in RMP — an error is an ordinary
envelope with `type: "rmp.error"`. This module defines the *payload* shape
convention for that type, plus the reserved infrastructure-level error codes
that the Hub itself may emit (when `source == "hub"`).

Product-level errors use the same payload shape but are sent by the product
itself as `source`, with a product-chosen `code` — RMP only reserves the
codes below for Hub-originated routing/infra failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# --- Reserved Hub-originated error codes ------------------------------------
# These describe infrastructure-level routing failures the Hub reports about
# its own delivery attempt (target offline, permission denied, malformed
# envelope, etc.) — not a product's business-level error.

TARGET_OFFLINE = "TARGET_OFFLINE"
PERMISSION_DENIED = "PERMISSION_DENIED"
MALFORMED_ENVELOPE = "MALFORMED_ENVELOPE"
UNKNOWN_TARGET = "UNKNOWN_TARGET"
CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"
TIMEOUT = "TIMEOUT"

RESERVED_ERROR_CODES = frozenset(
    {
        TARGET_OFFLINE,
        PERMISSION_DENIED,
        MALFORMED_ENVELOPE,
        UNKNOWN_TARGET,
        CAPABILITY_NOT_FOUND,
        VERSION_INCOMPATIBLE,
        TIMEOUT,
    }
)


class InvalidErrorPayloadError(ValueError):
    """Raised when an rmp.error payload fails its shape contract."""


@dataclass(frozen=True)
class RmpErrorPayload:
    """
    Payload shape for a `type: "rmp.error"` envelope.

    `code` is free-form for product-level errors; only the constants above
    are reserved for Hub-originated (`source == "hub"`) infra failures.
    """

    code: str
    message: str
    retryable: bool = False
    retry_after_ms: Optional[int] = None
    details: Optional[dict[str, Any]] = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise InvalidErrorPayloadError("'code' must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise InvalidErrorPayloadError("'message' must be a non-empty string")
        if self.retry_after_ms is not None and self.retry_after_ms < 0:
            raise InvalidErrorPayloadError("'retry_after_ms' must be >= 0")

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        data = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "retry_after_ms": self.retry_after_ms,
            "details": self.details,
        }
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data


def is_reserved_error_code(code: str) -> bool:
    """True if `code` is one of the Hub-reserved infra error codes."""
    return code in RESERVED_ERROR_CODES
