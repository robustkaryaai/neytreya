"""
The RMP envelope (RMP-SPEC §2) — the wire contract, and only the wire
contract. This module has no opinion on transport, auth, routing behavior,
or payload contents beyond "it's an object." See docs/RMP-SPEC.md for the
authoritative field-by-field rationale.

Implementation note: this is a dependency-free dataclass implementation
(no pydantic) so the `protocol/` package has zero third-party requirements
beyond the standard library. A pydantic-backed variant is a drop-in swap
behind the same public surface (RmpEnvelope, InvalidEnvelopeError,
to_wire/from_wire) if a project consuming this package wants that instead.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional

from .types import RESERVED_TYPES, is_namespaced_type
from .versioning import InvalidVersionError, parse_version

VALID_PRIORITIES = ("low", "normal", "high")
_CAPABILITY_PREFIX = "capability://"
_REQUIRED_TOP_LEVEL_FIELDS = {
    "id",
    "version",
    "timestamp",
    "source",
    "target",
    "type",
    "priority",
    "payload",
    "metadata",
}


class InvalidEnvelopeError(ValueError):
    """Raised when envelope construction/validation fails the RMP contract."""


def _default_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class RmpEnvelope:
    """
    The one envelope shape, everywhere. Every RMP message — request,
    response, event, error — is an instance of this model.

    `payload` and `metadata` are intentionally opaque `dict[str, Any]`:
    RMP defines the envelope, never the payload (Design Goal 3).
    """

    source: str
    target: str
    type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0"
    timestamp: str = field(default_factory=_default_timestamp)
    priority: str = "normal"
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate()

    # -- Validation -------------------------------------------------------

    def _validate(self) -> None:
        try:
            uuid.UUID(self.id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidEnvelopeError(f"'id' must be a UUID string, got {self.id!r}") from exc

        try:
            parse_version(self.version)
        except InvalidVersionError as exc:
            raise InvalidEnvelopeError(str(exc)) from exc

        normalized_ts = self.timestamp.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized_ts)
        except (ValueError, AttributeError) as exc:
            raise InvalidEnvelopeError(
                f"'timestamp' must be ISO 8601 UTC, got {self.timestamp!r}"
            ) from exc

        if not isinstance(self.source, str) or not self.source.strip():
            raise InvalidEnvelopeError("'source' must be a non-empty string")
        if not isinstance(self.target, str) or not self.target.strip():
            raise InvalidEnvelopeError("'target' must be a non-empty string")
        if not isinstance(self.type, str) or not self.type.strip():
            raise InvalidEnvelopeError("'type' must be a non-empty string")

        if self.priority not in VALID_PRIORITIES:
            raise InvalidEnvelopeError(
                f"'priority' must be one of {VALID_PRIORITIES}, got {self.priority!r}"
            )

        if not isinstance(self.payload, dict):
            raise InvalidEnvelopeError("'payload' must be an object")
        if not isinstance(self.metadata, dict):
            raise InvalidEnvelopeError("'metadata' must be an object")

        if self.target.startswith(_CAPABILITY_PREFIX):
            capability_name = self.target[len(_CAPABILITY_PREFIX):]
            if not capability_name:
                raise InvalidEnvelopeError(
                    "capability:// target must name a capability, e.g. "
                    "'capability://rkai.deep-reasoning'"
                )

    # -- Convenience helpers ------------------------------------------------

    def is_capability_target(self) -> bool:
        return self.target.startswith(_CAPABILITY_PREFIX)

    def capability_name(self) -> Optional[str]:
        """The bare capability string, or None if `target` is a direct address."""
        if not self.is_capability_target():
            return None
        return self.target[len(_CAPABILITY_PREFIX):]

    def is_reserved_type(self) -> bool:
        return self.type in RESERVED_TYPES

    def is_namespaced_type(self) -> bool:
        return is_namespaced_type(self.type)

    def in_response_to(self) -> Optional[str]:
        """Shorthand for the §3.1 correlation convention."""
        value = self.metadata.get("in_response_to")
        return value if isinstance(value, str) else None

    def resolved_for(self, direct_target: str) -> "RmpEnvelope":
        """
        Return a copy of this envelope with `target` rewritten to a direct
        product name. Per §4, a receiving product never has to handle a
        `capability://` target itself — the Registry/Hub resolves it and
        forwards with `target` already rewritten.
        """
        return replace(self, target=direct_target)

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the plain dict that goes on the wire as JSON."""
        return {
            "id": self.id,
            "version": self.version,
            "timestamp": self.timestamp,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "priority": self.priority,
            "payload": copy.deepcopy(self.payload),
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "RmpEnvelope":
        """Parse an incoming wire dict into a validated envelope."""
        if not isinstance(data, dict):
            raise InvalidEnvelopeError("envelope must be a JSON object")

        unknown = set(data.keys()) - _REQUIRED_TOP_LEVEL_FIELDS
        if unknown:
            raise InvalidEnvelopeError(f"unknown envelope field(s): {sorted(unknown)}")

        missing = {"source", "target", "type"} - set(data.keys())
        if missing:
            raise InvalidEnvelopeError(f"missing required envelope field(s): {sorted(missing)}")

        kwargs: dict[str, Any] = {
            "source": data["source"],
            "target": data["target"],
            "type": data["type"],
        }
        for optional_field in ("id", "version", "timestamp", "priority", "payload", "metadata"):
            if optional_field in data:
                kwargs[optional_field] = data[optional_field]

        return cls(**kwargs)
