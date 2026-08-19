import logging
from typing import Optional

from .manifest import ProductManifest
from .transport import AbstractTransport
from .exceptions import RegistrationFailedError, AuthenticationFailedError

try:
    from rexycore_auth.session_tokens import issue
except ImportError:
    # Minimal mock fallback for cases where auth isn't in path but they try to run anyway
    def issue(subject: str, **kwargs) -> str:
        return subject

class ConnectionManager:
    """
    Manages the lifecycle of connecting and authenticating over a transport.
    """
    def __init__(self, manifest: ProductManifest, transport: AbstractTransport, logger: logging.Logger):
        self.manifest = manifest
        self.transport = transport
        self.logger = logger

    async def connect_and_handshake(self, uri: str) -> None:
        """
        Executes the exact sequence required to establish a valid Hub session.
        """
        self.logger.info(f"Connecting to Hub at {uri}...")
        await self.transport.connect(uri)
        
        # Authenticate
        try:
            token = issue(subject=self.manifest.id)
            self.logger.debug("Successfully generated session token.")
        except Exception as e:
            self.logger.error(f"Failed to generate auth token: {e}")
            raise AuthenticationFailedError(f"Auth issue: {e}")

        # Register
        handshake = {
            "token": token,
            "registration": {
                "id": self.manifest.id,
                "version": self.manifest.version,
                "protocol": self.manifest.protocol
            }
        }
        
        try:
            await self.transport.send_json(handshake)
            self.logger.info("Sent registration handshake.")
        except Exception as e:
            raise RegistrationFailedError(f"Failed to send handshake: {e}")
