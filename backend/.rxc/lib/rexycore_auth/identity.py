"""
RMP-Auth: Identity — Ed25519 keypair management.

Each product has a long-lived Ed25519 keypair that establishes its identity
with the Hub. RMP itself (protocol/) never sees this — identity is
established once per connection at handshake time, then trusted for the
life of that connection (see RMP-SPEC §7 / §2 "what's deliberately not in
the envelope").

This module owns:
- generating/loading a product's Ed25519 keypair
- signing/verifying arbitrary bytes with it (used by session_tokens.py)
- OS keychain integration for the private key, with a file-based fallback
  for headless/CI environments where no OS keychain is available

It does NOT own:
- session tokens (session_tokens.py)
- permission grants (permissions.py)
- anything about the wire format (that's protocol/)
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_KEYCHAIN_SERVICE = "rexycore-auth"


class IdentityError(Exception):
    """Base class for identity-related failures."""


class KeyNotFoundError(IdentityError):
    """No stored keypair exists for the given product name."""


class SignatureVerificationError(IdentityError):
    """A signature did not verify against the claimed public key."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _un_b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


@dataclass(frozen=True)
class PublicIdentity:
    """The publicly-shareable half of a product's identity."""

    product_name: str
    public_key_b64: str

    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(_un_b64(self.public_key_b64))

    def verify(self, signature_b64: str, message: bytes) -> bool:
        """True if `signature_b64` is a valid Ed25519 signature over `message`."""
        try:
            self.public_key().verify(_un_b64(signature_b64), message)
            return True
        except InvalidSignature:
            return False


class ProductIdentity:
    """
    A product's full keypair. The private key never leaves this object
    once loaded — callers get signatures and the public identity, not the
    raw private key bytes.
    """

    def __init__(self, product_name: str, private_key: Ed25519PrivateKey):
        self._product_name = product_name
        self._private_key = private_key

    @property
    def product_name(self) -> str:
        return self._product_name

    @property
    def public_identity(self) -> PublicIdentity:
        public_bytes = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return PublicIdentity(self._product_name, _b64(public_bytes))

    def sign(self, message: bytes) -> str:
        """Sign `message`, returning a URL-safe base64 signature string."""
        return _b64(self._private_key.sign(message))

    @classmethod
    def generate(cls, product_name: str) -> "ProductIdentity":
        return cls(product_name, Ed25519PrivateKey.generate())

    # -- Serialization (for keystore backends) ---------------------------

    def _private_bytes_pem(self) -> bytes:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @classmethod
    def _from_private_bytes_pem(cls, product_name: str, pem: bytes) -> "ProductIdentity":
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise IdentityError(f"stored key for '{product_name}' is not Ed25519")
        return cls(product_name, key)


class KeyStore:
    """
    Loads/persists a product's private key.

    Tries the OS keychain first (via the optional `keyring` package); falls
    back to a file under `fallback_dir` (mode 0600) when no OS keychain
    backend is available — e.g. headless Linux CI. This fallback is
    explicit and file-permission-enforced rather than silent, since a
    product's private key is its entire identity.
    """

    def __init__(self, fallback_dir: Optional[Path] = None):
        self._fallback_dir = fallback_dir or (Path.home() / ".rexycore" / "keys")

    def _keyring_backend(self):
        try:
            import keyring  # type: ignore

            # Touching get_keyring() forces backend resolution; some
            # environments have keyring installed but no usable backend.
            keyring.get_keyring()
            return keyring
        except Exception:
            return None

    def load_or_create(self, product_name: str) -> ProductIdentity:
        try:
            return self.load(product_name)
        except KeyNotFoundError:
            identity = ProductIdentity.generate(product_name)
            self._save(identity)
            return identity

    def load(self, product_name: str) -> ProductIdentity:
        keyring = self._keyring_backend()
        if keyring is not None:
            pem_str = keyring.get_password(_KEYCHAIN_SERVICE, product_name)
            if pem_str is not None:
                return ProductIdentity._from_private_bytes_pem(
                    product_name, pem_str.encode("ascii")
                )

        path = self._fallback_path(product_name)
        if path.exists():
            return ProductIdentity._from_private_bytes_pem(product_name, path.read_bytes())

        raise KeyNotFoundError(f"no stored keypair for product '{product_name}'")

    def _save(self, identity: ProductIdentity) -> None:
        keyring = self._keyring_backend()
        pem = identity._private_bytes_pem()
        if keyring is not None:
            try:
                keyring.set_password(_KEYCHAIN_SERVICE, identity.product_name, pem.decode("ascii"))
                return
            except Exception:
                pass  # fall through to file-based storage

        path = self._fallback_path(identity.product_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pem)
        os.chmod(path, 0o600)

    def _fallback_path(self, product_name: str) -> Path:
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in product_name)
        return self._fallback_dir / f"{safe_name}.pem"
