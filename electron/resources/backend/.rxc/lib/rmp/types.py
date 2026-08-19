"""
RMP reserved `type` values.

RMP does NOT maintain a global enum of valid `type` values (see RMP-SPEC §3).
Only a small set of generic, product-agnostic types are reserved by RMP
itself, because they describe envelope-level plumbing rather than any one
product's business. Everything else is product-namespaced
(`<owning_product>.<verb_or_noun>`) and is opaque to RMP / the Hub.
"""

from __future__ import annotations

# --- Reserved type constants -------------------------------------------------

TYPE_ERROR = "rmp.error"
TYPE_ACK = "rmp.ack"
TYPE_PING = "rmp.ping"
TYPE_PONG = "rmp.pong"

RESERVED_TYPES = frozenset({TYPE_ERROR, TYPE_ACK, TYPE_PING, TYPE_PONG})


def is_reserved_type(type_: str) -> bool:
    """True if `type_` is one of RMP's own reserved plumbing types."""
    return type_ in RESERVED_TYPES


def is_namespaced_type(type_: str) -> bool:
    """
    True if `type_` follows the product-namespacing convention
    `<owning_product>.<verb_or_noun>` (a single dot separator, non-empty
    on both sides). This is a convention, not enforcement — RMP does not
    reject non-conforming types, but the SDK/tooling can use this to warn.
    """
    if type_ in RESERVED_TYPES:
        return True
    parts = type_.split(".", 1)
    return len(parts) == 2 and all(parts)
