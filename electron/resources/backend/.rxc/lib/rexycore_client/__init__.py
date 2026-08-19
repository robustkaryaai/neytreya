"""
RexyCore Client SDK
"""

from .manifest import ProductManifest
from .client import RexyCoreClient
from .exceptions import (
    RexyClientError,
    ConnectionFailedError,
    RegistrationFailedError,
    AuthenticationFailedError,
    TransportError,
    DeviceVerificationFailedError,
)
from .request_manager import RequestTimeoutError

__all__ = [
    "ProductManifest",
    "RexyCoreClient",
    "RexyClientError",
    "ConnectionFailedError",
    "RegistrationFailedError",
    "AuthenticationFailedError",
    "TransportError",
    "DeviceVerificationFailedError",
    "RequestTimeoutError",
]
