import asyncio
import logging
from typing import Callable, Coroutine

from .connection import ConnectionManager
from .dispatcher import EventDispatcher

class ReconnectManager:
    """
    Handles exponential backoff and transparent state restoration upon disconnect.
    """
    def __init__(self, connection_manager: ConnectionManager, dispatcher: EventDispatcher, logger: logging.Logger):
        self.connection_manager = connection_manager
        self.dispatcher = dispatcher
        self.logger = logger
        
        self.max_backoff = 60.0
        self.initial_backoff = 1.0
        self._running = True

    def stop(self):
        """Signals the loop to terminate."""
        self._running = False

    async def reconnect_loop(self, uri: str, listener_func: Callable[[], Coroutine], ack_event: asyncio.Event) -> None:
        """
        Continuously attempts to reconnect. Once connected, runs the listener loop.
        If the listener loop exits due to disconnect, starts backoff again.
        """
        backoff = self.initial_backoff
        
        while self._running:
            try:
                # Clear ACK flag for new connection
                ack_event.clear()
                
                # 1. Connect and Restore state
                await self.connection_manager.connect_and_handshake(uri)
                self.logger.info("Transport established, sent handshake.")
                backoff = self.initial_backoff
                
                # Fire on_connect event
                await self.dispatcher.dispatch_connect()
                
                # 2. Block on the listener loop
                # This will raise an exception or exit if the connection dies
                await listener_func()
                
            except Exception as e:
                if not self._running:
                    break
                self.logger.warning(f"Connection lost or failed: {e}")
                await self.dispatcher.dispatch_disconnect()
                
            if not self._running:
                break
                
            # 3. Exponential Backoff before retrying
            self.logger.info(f"Reconnecting in {backoff} seconds...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff)
