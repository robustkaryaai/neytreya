import asyncio
import logging
from typing import Callable, Coroutine, Dict, Any, Optional

from .manifest import ProductManifest
from .config import ConfigLoader, RuntimeConfig
from .transport import AbstractTransport, WebSocketTransport
from .connection import ConnectionManager
from .dispatcher import EventDispatcher
from .request_manager import RequestManager
from .heartbeat import HeartbeatManager
from .reconnect import ReconnectManager
from .device_verification import DeviceVerifier
from .logging import configure_logger
from .exceptions import ConnectionFailedError

try:
    from rmp import RmpEnvelope, InvalidEnvelopeError
except ImportError:
    class RmpEnvelope: pass
    class InvalidEnvelopeError(Exception): pass

class RexyCoreClient:
    """
    Official RexyCore Client SDK.
    Completely abstracts connection, auth, registration, capability advertising,
    heartbeats, automatic reconnections, and request-response patterns.
    """
    def __init__(
        self,
        manifest: ProductManifest,
        hub_uri: Optional[str] = None,
        config: Optional[RuntimeConfig] = None,
        transport: Optional[AbstractTransport] = None,
        log_level: int = logging.INFO
    ):
        self.manifest = manifest
        # Load configuration, allowing overrides
        self.config = config or ConfigLoader.load()
        self.hub_uri = hub_uri or self.config.hub_uri
        
        self.logger = configure_logger(manifest.id, level=log_level)
        
        # Internals
        self.transport = transport or WebSocketTransport()
        self.connection_manager = ConnectionManager(self.manifest, self.transport, self.logger)
        self.dispatcher = EventDispatcher(self.logger)
        self.request_manager = RequestManager(self.logger)
        
        self.heartbeat = HeartbeatManager(self.transport, self.manifest.id, self.logger)
        self.reconnect_manager = ReconnectManager(self.connection_manager, self.dispatcher, self.logger)
        
        self.device_verifier = DeviceVerifier(self.config, self.logger)
        
        self._main_task: Optional[asyncio.Task] = None
        self._is_running = False
        
        # Synchronization event for connect()
        self._registration_ack_event = asyncio.Event()

    # --- Public Decorators ---

    def on_connect(self, func: Callable[[], Coroutine]):
        """Triggered upon successful connection (and after reconnection restores)."""
        return self.dispatcher.register_on_connect(func)

    def on_disconnect(self, func: Callable[[], Coroutine]):
        """Triggered when connection is unexpectedly lost."""
        return self.dispatcher.register_on_disconnect(func)

    def on_error(self, func: Callable[[Exception], Coroutine]):
        return self.dispatcher.register_on_error(func)

    def on_message(self, msg_type: str):
        """Triggered when an incoming message matches the specified RMP type."""
        return self.dispatcher.register_on_message(msg_type)

    # --- Public API ---

    async def connect(self):
        """
        Connects to the Hub and maintains the connection autonomously.
        Verifies device legitimacy before starting the background loop.
        Blocks until the Hub explicitly acknowledges the registration.
        """
        # 1. Device Legitimacy Verification
        self.logger.info("Verifying device legitimacy...")
        await self.device_verifier.verify()
        
        # 2. Start Background Lifecycle
        self._is_running = True
        self._registration_ack_event.clear()
        
        self._main_task = asyncio.create_task(
            self.reconnect_manager.reconnect_loop(self.hub_uri, self._client_listener_loop, self._registration_ack_event)
        )
        self.logger.info("RexyCore Client connecting to Hub...")
        
        # 3. Block until registration is acknowledged by the Hub
        await self._registration_ack_event.wait()
        self.logger.info("Client registration fully synchronized and acknowledged by Hub.")

    async def close(self):
        """
        Gracefully terminates the connection and background loops.
        """
        self.logger.info("Shutting down RexyCore Client...")
        self._is_running = False
        
        if self.reconnect_manager:
            self.reconnect_manager.stop()
            
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
                
        await self.heartbeat.stop()
        await self.transport.close()
        self.logger.info("Client shutdown complete.")

    async def send(self, target: str, msg_type: str, payload: Dict[str, Any], metadata: Dict[str, Any] = None) -> None:
        """Fire-and-forget message sending."""
        if not self.transport.is_connected():
            raise ConnectionFailedError("Cannot send: disconnected.")
            
        envelope = RmpEnvelope(
            source=self.manifest.id,
            target=target,
            type=msg_type,
            payload=payload,
            metadata=metadata or {}
        )
        await self.transport.send_json(envelope.to_wire())
        self.logger.debug(f"Sent {msg_type} to {target}")

    async def request(self, target: str, msg_type: str, payload: Dict[str, Any], timeout: float = 10.0) -> RmpEnvelope:
        """Request-Response pattern generating correlation_id."""
        correlation_id, future = self.request_manager.create_request()
        
        metadata = {"correlation_id": correlation_id}
        await self.send(target, msg_type, payload, metadata=metadata)
        
        response_env = await self.request_manager.wait_for_response(correlation_id, timeout=timeout)
        return response_env

    # --- Internal Background Loop ---

    async def _client_listener_loop(self):
        """The core listener."""
        self.heartbeat.start()
        
        try:
            while self._is_running and self.transport.is_connected():
                raw_dict = await self.transport.receive_json()
                self.heartbeat.record_activity()
                
                # Check for Hub Ping
                if raw_dict.get("type") == "rmp.ping":
                    await self.heartbeat.handle_ping()
                    continue
                    
                # Check for Registration Ack
                if raw_dict.get("type") == "rmp.registration.ack":
                    self.logger.debug("Received registration ACK from Hub.")
                    self._registration_ack_event.set()
                    # Trigger any user registered hooks
                    await self.dispatcher.dispatch_registered()
                    continue
                    
                # Parse Envelope
                try:
                    envelope = RmpEnvelope.from_wire(raw_dict)
                except InvalidEnvelopeError as e:
                    self.logger.error(f"Malformed RMP Envelope: {e}")
                    continue
                    
                # 1. Check if it's a response to a pending request()
                if self.request_manager.handle_incoming_envelope(envelope):
                    continue
                    
                # 2. Otherwise dispatch to generic event handlers
                await self.dispatcher.dispatch_message(envelope)
                
        finally:
            await self.heartbeat.stop()
