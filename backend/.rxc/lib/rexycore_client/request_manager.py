import asyncio
import uuid
import logging
from typing import Dict, Optional, Tuple

try:
    from rmp import RmpEnvelope
except ImportError:
    class RmpEnvelope: pass

class RequestTimeoutError(Exception):
    pass

class RequestManager:
    """
    Manages request-response correlation via async Futures.
    Uses metadata["correlation_id"] as per RMP design alignment.
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        # map: correlation_id -> Future
        self._pending_requests: Dict[str, asyncio.Future] = {}

    def create_request(self) -> Tuple[str, asyncio.Future]:
        """Creates a correlation ID and a Future for awaiting the response."""
        correlation_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[correlation_id] = future
        return correlation_id, future

    async def wait_for_response(self, correlation_id: str, timeout: float = 10.0) -> RmpEnvelope:
        """Awaits the response with a timeout, cleaning up afterwards."""
        future = self._pending_requests.get(correlation_id)
        if not future:
            raise ValueError(f"No pending request for {correlation_id}")
            
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.warning(f"Request {correlation_id} timed out.")
            raise RequestTimeoutError(f"Request {correlation_id} timed out after {timeout}s.")
        finally:
            self._pending_requests.pop(correlation_id, None)

    def handle_incoming_envelope(self, envelope: RmpEnvelope) -> bool:
        """
        Checks if the envelope is a response to a pending request.
        Returns True if handled (meaning the dispatcher shouldn't route it generally).
        """
        metadata = getattr(envelope, "metadata", {})
        correlation_id = metadata.get("correlation_id")
        
        if correlation_id and correlation_id in self._pending_requests:
            future = self._pending_requests[correlation_id]
            if not future.done():
                future.set_result(envelope)
            return True
        return False
