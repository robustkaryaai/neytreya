"""
RMP-Auth: Session tokens — short-lived, per-connection identity proof.

Flow this module supports (independent of transport — RMP-SPEC §7 says
auth is a transport-session concern, not part of the envelope):

1. Product connects to the Hub over whatever transport (UDS/WS/etc).
2. Product proves it holds the private key for its registered
   `product_name` by signing a Hub-issued challenge (`sign_challenge`),
   OR the Hub trusts a prior handshake and issues a `SessionToken`
   directly (`issue`).
3. Hub verifies the token on subsequent messages via `verify` — this is
   what lets RMP's envelope itself stay free of any `auth` field: the
   Hub already knows which authenticated `source` identity is attached
   to a given connection before it ever inspects an envelope.

Tokens are short-lived and hold no secret material themselves (they're a
signed claim, not a credential) — a leaked token is only useful until
`expires_at`, and only for the product+connection it was scoped to.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .identity import PublicIdentity, ProductIdentity

DEFAULT_TOKEN_TTL_SECONDS = 15 * 60  # 15 minutes


class SessionTokenError(Exception):
    """Base class for session token failures."""


class TokenExpiredError(SessionTokenError):
    pass


class TokenSignatureInvalidError(SessionTokenError):
    pass


@dataclass(frozen=True)
class SessionToken:
    """
    A signed, short-lived claim of identity for one connection.

    `token_id` and `connection_id` let the Hub bind a token to exactly one
    live connection, so a copied token can't be replayed on a second
    connection concurrently (the Hub's connection_manager enforces that
    binding — this module only defines and verifies the token shape).
    """

    product_name: str
    connection_id: str
    token_id: str
    issued_at: float
    expires_at: float
    signature_b64: str

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def _signed_payload(self) -> bytes:
        # Deterministic, canonical encoding of everything except the
        # signature itself -- this is exactly what was signed by `issue`.
        payload = {
            "product_name": self.product_name,
            "connection_id": self.connection_id,
            "token_id": self.token_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_dict(self) -> dict:
        return {
            "product_name": self.product_name,
            "connection_id": self.connection_id,
            "token_id": self.token_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionToken":
        required = {"product_name", "connection_id", "token_id", "issued_at", "expires_at", "signature"}
        missing = required - set(data.keys())
        if missing:
            raise SessionTokenError(f"session token missing field(s): {sorted(missing)}")
        return cls(
            product_name=data["product_name"],
            connection_id=data["connection_id"],
            token_id=data["token_id"],
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
            signature_b64=data["signature"],
        )


def issue(
    identity: ProductIdentity,
    connection_id: str,
    ttl_seconds: float = DEFAULT_TOKEN_TTL_SECONDS,
    now: Optional[float] = None,
) -> SessionToken:
    """
    Issue a new session token, signed by `identity`'s private key.

    Called by the product's SDK at handshake time (or by the Hub itself,
    if the Hub is the one holding product keys in a given deployment
    model — RMP-Auth doesn't mandate which side issues, only the shape).
    """
    issued_at = now if now is not None else time.time()
    token = SessionToken(
        product_name=identity.product_name,
        connection_id=connection_id,
        token_id=str(uuid.uuid4()),
        issued_at=issued_at,
        expires_at=issued_at + ttl_seconds,
        signature_b64="",
    )
    signature = identity.sign(token._signed_payload())
    return SessionToken(
        product_name=token.product_name,
        connection_id=token.connection_id,
        token_id=token.token_id,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        signature_b64=signature,
    )


def verify(
    token: SessionToken,
    public_identity: PublicIdentity,
    expected_connection_id: Optional[str] = None,
    now: Optional[float] = None,
) -> None:
    """
    Verify `token` was legitimately issued by the holder of
    `public_identity`'s private key, is unexpired, and (if given) is bound
    to `expected_connection_id`. Raises on any failure; returns None on
    success.
    """
    if token.product_name != public_identity.product_name:
        raise TokenSignatureInvalidError(
            f"token claims product '{token.product_name}' but was checked "
            f"against identity '{public_identity.product_name}'"
        )
    if expected_connection_id is not None and token.connection_id != expected_connection_id:
        raise TokenSignatureInvalidError(
            "token is not bound to the expected connection"
        )
    if not public_identity.verify(token.signature_b64, token._signed_payload()):
        raise TokenSignatureInvalidError("token signature does not verify")
    if token.is_expired(now):
        raise TokenExpiredError(
            f"token for '{token.product_name}' expired at {token.expires_at}"
        )
