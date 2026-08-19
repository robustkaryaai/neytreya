"""
RMP-Auth: Permissions — what one product is allowed to do to/via another.

This is deliberately separate from identity/session_tokens: knowing *who*
sent an envelope (identity) is not the same question as whether *that
sender* is allowed to reach a given `target`/`type` (permissions). The Hub
enforces this at the connection_manager layer (per RMP-SPEC §7 — "whether
a Hub enforces permissions" is Hub behavior); this module only defines the
grant model and the (side-effect-free) decision function.

Grants are scoped by (source, target, type_pattern) so a product can be
allowed to send `malus.*` to `rk-ai` without also being allowed to send
`malus.admin_reset`, etc. A consent UI hook is provided as a callback
protocol so a product embedding this (e.g. a local desktop Hub) can prompt
a human the first time an ungranted request is seen, without this module
knowing anything about how that UI is actually rendered.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class GrantScope(str, Enum):
    """How broad a single grant is."""

    ONCE = "once"          # valid for exactly one message, then consumed
    SESSION = "session"    # valid for the lifetime of one connection
    PERSISTENT = "persistent"  # valid until explicitly revoked


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # no matching grant or denial on file — defer to consent hook


@dataclass(frozen=True)
class PermissionGrant:
    """
    One rule: `source` may send messages of `type_pattern` to `target`.

    `type_pattern` supports simple glob matching (`fnmatch`), e.g.
    `"malus.*"` or `"*"`. An explicit grant with `allow=False` is a standing
    denial (distinct from "no grant on file", which resolves to ASK).
    """

    source: str
    target: str
    type_pattern: str
    allow: bool
    scope: GrantScope = GrantScope.PERSISTENT
    granted_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

    def matches(self, source: str, target: str, type_: str) -> bool:
        return (
            self.source == source
            and self.target == target
            and fnmatch.fnmatchcase(type_, self.type_pattern)
        )

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at


ConsentHook = Callable[[str, str, str], bool]
"""
A callback `(source, target, type_) -> bool` invoked when no grant or
denial is on file. Returning True records an implicit one-time allow for
that exact call; it does NOT persist a grant — callers that want a
standing grant should call `PermissionEngine.grant(...)` explicitly (e.g.
from a "always allow" consent UI button), keeping "allow this once" and
"remember this choice" as separate, deliberate actions.
"""


class PermissionEngine:
    """
    Holds a set of grants for one Hub/deployment and answers permission
    checks against them. Pure decision logic — no I/O, no persistence;
    a Hub wires this to its own storage and to a real consent UI.
    """

    def __init__(self, consent_hook: Optional[ConsentHook] = None):
        self._grants: list[PermissionGrant] = []
        self._consent_hook = consent_hook

    def grant(self, grant: PermissionGrant) -> None:
        self._grants.append(grant)

    def revoke(self, source: str, target: str, type_pattern: str) -> int:
        """Remove matching grants (any scope). Returns count removed."""
        before = len(self._grants)
        self._grants = [
            g
            for g in self._grants
            if not (g.source == source and g.target == target and g.type_pattern == type_pattern)
        ]
        return before - len(self._grants)

    def _active_grants(self, now: Optional[float] = None) -> list[PermissionGrant]:
        return [g for g in self._grants if not g.is_expired(now)]

    def check(self, source: str, target: str, type_: str, now: Optional[float] = None) -> PermissionDecision:
        """
        Decide whether `source` may send a `type_`-typed message to
        `target`. Most-specific-pattern-wins is NOT implemented here —
        matching grants are evaluated in the order added, first match
        wins, so callers should add explicit denials before broad allows
        if that ordering matters for their deployment.
        """
        matching = [g for g in self._active_grants(now) if g.matches(source, target, type_)]
        if not matching:
            return PermissionDecision.ASK
        return PermissionDecision.ALLOW if matching[0].allow else PermissionDecision.DENY

    def check_with_consent(self, source: str, target: str, type_: str, now: Optional[float] = None) -> bool:
        """
        Convenience wrapper: returns a plain bool, consulting the consent
        hook (if any) when the decision is ASK. Raises if the decision is
        ASK and no consent hook is configured, rather than silently
        defaulting either way.
        """
        decision = self.check(source, target, type_, now)
        if decision == PermissionDecision.ALLOW:
            return True
        if decision == PermissionDecision.DENY:
            return False
        if self._consent_hook is None:
            raise PermissionError(
                f"no grant on file for {source} -> {target} ({type_}) and no consent hook configured"
            )
        return self._consent_hook(source, target, type_)

    def active_grants_for(self, source: str, target: str) -> list[PermissionGrant]:
        """All active grants between a given source/target pair, for display in a consent/settings UI."""
        return [g for g in self._active_grants() if g.source == source and g.target == target]
