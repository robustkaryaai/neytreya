import logging
from typing import Callable, Coroutine, Dict, Any, Optional

try:
    from rmp import RmpEnvelope
except ImportError:
    class RmpEnvelope: pass

class EventDispatcher:
    """
    Routes events (connect, disconnect, registered, messages) to registered asynchronous handlers.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        
        self.on_connect_handler: Optional[Callable[[], Coroutine]] = None
        self.on_disconnect_handler: Optional[Callable[[], Coroutine]] = None
        self.on_registered_handler: Optional[Callable[[], Coroutine]] = None
        self.on_error_handler: Optional[Callable[[Exception], Coroutine]] = None
        
        self._message_handlers: Dict[str, Callable[[RmpEnvelope], Coroutine]] = {}
        self._default_message_handler: Optional[Callable[[RmpEnvelope], Coroutine]] = None

    def register_on_connect(self, func: Callable[[], Coroutine]):
        self.on_connect_handler = func
        return func

    def register_on_disconnect(self, func: Callable[[], Coroutine]):
        self.on_disconnect_handler = func
        return func

    def register_on_registered(self, func: Callable[[], Coroutine]):
        self.on_registered_handler = func
        return func

    def register_on_error(self, func: Callable[[Exception], Coroutine]):
        self.on_error_handler = func
        return func

    def register_on_message(self, msg_type: str):
        def decorator(func: Callable[[RmpEnvelope], Coroutine]):
            self._message_handlers[msg_type] = func
            return func
        return decorator

    # --- Dispatch Methods ---

    async def dispatch_connect(self):
        if self.on_connect_handler:
            await self.on_connect_handler()

    async def dispatch_disconnect(self):
        if self.on_disconnect_handler:
            await self.on_disconnect_handler()

    async def dispatch_registered(self):
        if self.on_registered_handler:
            await self.on_registered_handler()

    async def dispatch_error(self, error: Exception):
        if self.on_error_handler:
            await self.on_error_handler(error)

    async def dispatch_message(self, envelope: RmpEnvelope):
        handler = self._message_handlers.get(envelope.type, self._default_message_handler)
        if handler:
            try:
                await handler(envelope)
            except Exception as e:
                self.logger.error(f"Error executing handler for {envelope.type}: {e}")
                await self.dispatch_error(e)
        else:
            self.logger.debug(f"Unhandled message type: {envelope.type}")
