"""
RMP — RexyCore Message Protocol.

The wire contract, and only the wire contract. See docs/RMP-SPEC.md for the
authoritative spec. This package intentionally has no knowledge of
transport, auth, registry resolution, or Hub behavior.
"""

from .envelope import InvalidEnvelopeError, RmpEnvelope
from .errors import (
    CAPABILITY_NOT_FOUND,
    MALFORMED_ENVELOPE,
    PERMISSION_DENIED,
    RESERVED_ERROR_CODES,
    TARGET_OFFLINE,
    TIMEOUT,
    UNKNOWN_TARGET,
    VERSION_INCOMPATIBLE,
    RmpErrorPayload,
    is_reserved_error_code,
)
from .types import (
    RESERVED_TYPES,
    TYPE_ACK,
    TYPE_ERROR,
    TYPE_PING,
    TYPE_PONG,
    is_namespaced_type,
    is_reserved_type,
)
from .versioning import InvalidVersionError, RmpVersion, is_compatible, parse_version

__all__ = [
    "RmpEnvelope",
    "InvalidEnvelopeError",
    "RmpErrorPayload",
    "is_reserved_error_code",
    "RESERVED_ERROR_CODES",
    "TARGET_OFFLINE",
    "PERMISSION_DENIED",
    "MALFORMED_ENVELOPE",
    "UNKNOWN_TARGET",
    "CAPABILITY_NOT_FOUND",
    "VERSION_INCOMPATIBLE",
    "TIMEOUT",
    "TYPE_ERROR",
    "TYPE_ACK",
    "TYPE_PING",
    "TYPE_PONG",
    "RESERVED_TYPES",
    "is_reserved_type",
    "is_namespaced_type",
    "RmpVersion",
    "parse_version",
    "is_compatible",
    "InvalidVersionError",
    "build_error_envelope",
]


def build_error_envelope(
    *,
    source: str,
    target: str,
    code: str,
    message: str,
    in_response_to: str | None = None,
    retryable: bool = False,
    retry_after_ms: int | None = None,
    details: dict | None = None,
    priority: str = "high",
) -> RmpEnvelope:
    """
    Convenience builder for a `type: "rmp.error"` envelope (§3.2).

    `source` is either "hub" (infra-level routing failure) or a product
    name (product-level business error) — RMP doesn't distinguish the two
    structurally, only by convention.
    """
    payload = RmpErrorPayload(
        code=code,
        message=message,
        retryable=retryable,
        retry_after_ms=retry_after_ms,
        details=details,
    )
    metadata = {"in_response_to": in_response_to} if in_response_to else {}
    return RmpEnvelope(
        source=source,
        target=target,
        type=TYPE_ERROR,
        priority=priority,
        payload=payload.to_dict(),
        metadata=metadata,
    )
