"""
RMP version negotiation helpers.

RMP's `version` field is a semver string, independent of the Hub's release
version and any individual product's version (see RMP-SPEC §6).

Compatibility rule:
- Minor bumps (1.0 -> 1.1) are additive-only: new optional envelope fields,
  new reserved rmp.* types. A connection negotiated at 1.0 can safely talk
  to a peer that supports 1.1, as long as neither side requires the new
  optional fields.
- Major bumps (1.x -> 2.0) may change required-field shape and are not
  silently compatible.

The Hub is expected to support at least N-1 major RMP versions concurrently
so products can upgrade independently without a forced simultaneous cutover.
This module only implements the pure version-comparison logic; it says
nothing about *how* a Hub negotiates or stores per-connection version state
(that's Hub/RMP-Auth behavior, not protocol).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


class InvalidVersionError(ValueError):
    """Raised when a version string doesn't parse as RMP semver."""


@dataclass(frozen=True, order=True)
class RmpVersion:
    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, version: str) -> "RmpVersion":
        match = _SEMVER_RE.match(version.strip())
        if not match:
            raise InvalidVersionError(
                f"'{version}' is not a valid RMP version string "
                "(expected 'MAJOR.MINOR' or 'MAJOR.MINOR.PATCH')"
            )
        major, minor, patch = match.groups()
        return cls(int(major), int(minor), int(patch or 0))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(version: str) -> RmpVersion:
    """Parse a version string, raising InvalidVersionError if malformed."""
    return RmpVersion.parse(version)


def is_compatible(sender_version: str, receiver_supported: str) -> bool:
    """
    True if an envelope declaring `sender_version` can be safely accepted
    by a peer that supports up to `receiver_supported`.

    Compatible when major versions match and the sender's version is not
    newer (in minor/patch) than what the receiver supports — a receiver
    can always understand an older-or-equal minor/patch within the same
    major line (additive-only rule), but cannot guarantee understanding
    fields introduced by a *newer* minor version it hasn't been updated to
    support.
    """
    sender = parse_version(sender_version)
    receiver = parse_version(receiver_supported)
    if sender.major != receiver.major:
        return False
    return (sender.minor, sender.patch) <= (receiver.minor, receiver.patch)


def supports_major(version: str, supported_majors: list[int]) -> bool:
    """True if `version`'s major component is in `supported_majors`."""
    return parse_version(version).major in supported_majors
