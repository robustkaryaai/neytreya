import abc
import json
import websockets
from typing import Dict, Any, Optional

from .exceptions import TransportError, ConnectionFailedError

class AbstractTransport(abc.ABC):
    """
    Abstract interface for any transport mechanism used by the Client SDK.
    """
    @abc.abstractmethod
    async def connect(self, uri: str) -> None:
        """Establish a connection to the provided URI."""
        pass

    @abc.abstractmethod
    async def send_json(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload over the transport."""
        pass

    @abc.abstractmethod
    async def receive_json(self) -> Dict[str, Any]:
        """Receive a JSON payload from the transport."""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the transport connection."""
        pass

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if currently connected."""
        pass

class WebSocketTransport(AbstractTransport):
    """
    Version 1 standard WebSocket transport.
    """
    def __init__(self):
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self, uri: str) -> None:
        try:
            self.ws = await websockets.connect(uri)
        except Exception as e:
            raise ConnectionFailedError(f"WebSocket connection to {uri} failed: {e}")

    async def send_json(self, payload: Dict[str, Any]) -> None:
        if not self.ws or self.ws.closed:
            raise TransportError("Cannot send: WebSocket is closed.")
        try:
            await self.ws.send(json.dumps(payload))
        except websockets.ConnectionClosed:
            raise TransportError("Connection closed while sending.")

    async def receive_json(self) -> Dict[str, Any]:
        if not self.ws or self.ws.closed:
            raise TransportError("Cannot receive: WebSocket is closed.")
        try:
            raw_msg = await self.ws.recv()
            return json.loads(raw_msg)
        except websockets.ConnectionClosed:
            raise TransportError("Connection closed while receiving.")
        except json.JSONDecodeError as e:
            raise TransportError(f"Received malformed JSON: {e}")

    async def close(self) -> None:
        if self.ws and not self.ws.closed:
            await self.ws.close()

    def is_connected(self) -> bool:
        return self.ws is not None and not self.ws.closed
