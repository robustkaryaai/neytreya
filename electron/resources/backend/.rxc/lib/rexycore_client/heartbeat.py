import asyncio
import logging
import json
import time
from typing import Optional

from .transport import AbstractTransport
from .exceptions import TransportError

class HeartbeatManager:
    """
    Manages sending heartbeats to the Hub and detecting timeouts.
    """
    def __init__(self, transport: AbstractTransport, product_id: str, logger: logging.Logger, ping_interval: float = 30.0, timeout: float = 10.0):
        self.transport = transport
        self.product_id = product_id
        self.logger = logger
        self.ping_interval = ping_interval
        self.timeout = timeout
        
        self._last_activity = time.time()
        self._waiting_pong = False
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def record_activity(self):
        """Called whenever any message is received from the Hub."""
        self._last_activity = time.time()
        self._waiting_pong = False

    async def handle_ping(self):
        """Called when the Hub sends a ping. We must reply with pong."""
        pong_msg = {
            "source": self.product_id,
            "target": "hub",
            "type": "rmp.pong",
            "payload": {}
        }
        await self.transport.send_json(pong_msg)
        self.logger.debug("Sent heartbeat PONG to Hub.")

    def start(self):
        self._running = True
        self._last_activity = time.time()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            await asyncio.sleep(self.ping_interval)
            
            if not self.transport.is_connected():
                continue
                
            now = time.time()
            if self._waiting_pong:
                if now - self._last_activity > self.timeout:
                    self.logger.error("Heartbeat timeout. Hub is unresponsive.")
                    await self.transport.close() # Force close to trigger reconnect
                    self._waiting_pong = False
            else:
                # Send our own PING to keep connection alive if idle
                ping_msg = {
                    "source": self.product_id,
                    "target": "hub",
                    "type": "rmp.ping",
                    "payload": {}
                }
                try:
                    await self.transport.send_json(ping_msg)
                    self._waiting_pong = True
                    self.logger.debug("Sent heartbeat PING to Hub.")
                except Exception as e:
                    self.logger.error(f"Failed to send heartbeat PING: {e}")
                    await self.transport.close()
