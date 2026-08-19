"""
RMP-Auth — identity, sessions, and permission grants.

Independent, separately-versioned project consumed by the Hub (per
RMP-SPEC §7 / the project restructure). Depends on `protocol/` for
nothing — auth concerns are transport-session-level, established before
any RMP envelope is ever sent, and RMP's envelope carries no `auth` field
by design.
"""

from .identity import (
    IdentityError,
    KeyNotFoundError,
    KeyStore,
    ProductIdentity,
    PublicIdentity,
    SignatureVerificationError,
)
from .permissions import (
    ConsentHook,
    GrantScope,
    PermissionDecision,
    PermissionEngine,
    PermissionGrant,
)
from .session_tokens import (
    DEFAULT_TOKEN_TTL_SECONDS,
    SessionToken,
    SessionTokenError,
    TokenExpiredError,
    TokenSignatureInvalidError,
    issue,
    verify,
)

__all__ = [
    "ProductIdentity",
    "PublicIdentity",
    "KeyStore",
    "IdentityError",
    "KeyNotFoundError",
    "SignatureVerificationError",
    "SessionToken",
    "issue",
    "verify",
    "SessionTokenError",
    "TokenExpiredError",
    "TokenSignatureInvalidError",
    "DEFAULT_TOKEN_TTL_SECONDS",
    "PermissionGrant",
    "PermissionEngine",
    "PermissionDecision",
    "GrantScope",
    "ConsentHook",
]
