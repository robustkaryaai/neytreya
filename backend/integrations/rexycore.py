"""
integrations/rexycore.py
────────────────────────
Neytreya's connection to the RexyCore ecosystem.

Architecture:
  - Neytreya registers as "rexycore.neytreya" on the local Hub.
  - When stuck is detected AND RK AI is online → ask user consent.
  - If user agrees → send structured context via RMP to "rexycore.rk-ai".
  - If RK AI is offline → Neytreya handles it with a natural observation.
  - Hub-down → completely silent, Neytreya works standalone.

All communication is through the official RexyCoreClient SDK.
No custom networking. No HTTP polling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)

# ── Lazy imports (only available after bootstrap) ───────────────────────────

_SDK_AVAILABLE = False

try:
    from rexycore_client import RexyCoreClient, ProductManifest
    from rexycore_client.exceptions import (
        ConnectionFailedError,
        DeviceVerificationFailedError,
    )
    from rexycore_client.request_manager import RequestTimeoutError
    _SDK_AVAILABLE = True
except ImportError:
    pass  # bootstrap not run yet or unavailable — graceful degradation


# ── Constants ────────────────────────────────────────────────────────────────

PRODUCT_ID      = "rexycore.neytreya"
PRODUCT_VERSION = "1.0.0"

# RMP message types Neytreya sends
MSG_CONTEXT_REQUEST  = "neytreya.context_request"
MSG_PING             = "neytreya.ping"

# RMP message types Neytreya receives
MSG_HELP_OFFER       = "rkai.help_offer"
MSG_HELP_DECLINE     = "rkai.help_decline"
MSG_PONG             = "rkai.pong"

MSG_SYSTEM_STATE_REQUEST  = "neytreya.system_state_request"
MSG_SYSTEM_STATE_RESPONSE = "neytreya.system_state_response"

# Target IDs in the ecosystem
TARGET_RK_AI         = "rexycore.rk-ai"

# How long to wait for RK AI ping response
PING_TIMEOUT = 2.5


# ── Link ─────────────────────────────────────────────────────────────────────

class RexyCoreLink:
    """
    Manages Neytreya's presence on the RexyCore Hub.

    Lifetime: created at backend startup, lives for the process lifetime.
    The Hub being unavailable is not an error — Neytreya is fully
    standalone. The link silently retries in the background.
    """

    def __init__(self) -> None:
        self._client: Optional["RexyCoreClient"] = None
        self._connected = False
        self._connect_task: Optional[asyncio.Task] = None

        # Callbacks registered by main.py / observation engine
        self._on_help_offer:           Optional[Callable[[Dict], Coroutine]] = None
        self._on_help_decline:         Optional[Callable[[Dict], Coroutine]] = None
        self._on_system_state_request: Optional[Callable[[], Coroutine[Any, Any, Dict[str, Any]]]] = None

    # ── Public lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """
        Fire-and-forget: try to connect to the Hub in the background.
        Neytreya does NOT wait for this — it continues normally if the Hub
        is absent.
        """
        if not _SDK_AVAILABLE:
            logger.debug("[rxc] SDK not available — running standalone.")
            return
        self._connect_task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        if self._connect_task:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        if self._client and self._connected:
            try:
                await self._client.close()
            except Exception:
                pass
        self._connected = False
        logger.info("[rxc] Disconnected from Hub.")

    # ── Public queries ───────────────────────────────────────────────────

    @property
    def is_hub_connected(self) -> bool:
        return self._connected

    async def is_rk_ai_available(self) -> bool:
        """
        Returns True only if Hub is up AND RK AI is registered on it.
        Uses a request-response ping with a short timeout.
        """
        if not self._connected or self._client is None:
            return False
        try:
            await self._client.request(
                target=TARGET_RK_AI,
                msg_type=MSG_PING,
                payload={"from": PRODUCT_ID},
                timeout=PING_TIMEOUT,
            )
            return True
        except Exception:
            return False

    # ── Public actions ───────────────────────────────────────────────────

    async def send_stuck_context(
        self,
        context: Dict[str, Any],
        inference: Dict[str, Any],
        signals: list[str],
    ) -> bool:
        """
        Send structured stuck-context to RK AI via the Hub.
        Returns True if sent successfully, False otherwise.
        Call this only after confirming the user wants RK AI's help.
        """
        if not self._connected or self._client is None:
            return False
        try:
            await self._client.send(
                target=TARGET_RK_AI,
                msg_type=MSG_CONTEXT_REQUEST,
                payload={
                    "request_type": "stuck_context",
                    "context":      context,
                    "inference":    inference,
                    "signals":      signals,
                    "source_app":   context.get("app", "unknown"),
                    "timestamp":    datetime.utcnow().isoformat() + "Z",
                },
            )
            logger.info("[rxc] Stuck context sent to RK AI.")
            return True
        except Exception as exc:
            logger.warning("[rxc] Failed to send context to RK AI: %s", exc)
            return False

    # ── Event hooks ──────────────────────────────────────────────────────

    def on_help_offer(self, callback: Callable[[Dict], Coroutine]) -> None:
        """Register a callback for when RK AI offers help (rkai.help_offer)."""
        self._on_help_offer = callback

    def on_help_decline(self, callback: Callable[[Dict], Coroutine]) -> None:
        """Register a callback for when RK AI declines (rkai.help_decline)."""
        self._on_help_decline = callback

    def on_system_state_request(self, callback: Callable[[], Coroutine[Any, Any, Dict[str, Any]]]) -> None:
        """Register a callback to fulfill system state observation requests."""
        self._on_system_state_request = callback

    # ── Internal ─────────────────────────────────────────────────────────

    async def _connect_loop(self) -> None:
        """
        Try to connect to the Hub. On failure, back off and retry quietly.
        This is completely invisible to the user — it's just background
        infrastructure that activates when the Hub is running.
        """
        backoff = 5.0

        while True:
            try:
                await self._connect()
                backoff = 5.0  # reset on success
                # Keep task alive while connected
                while self._connected:
                    await asyncio.sleep(10)

            except asyncio.CancelledError:
                return

            except DeviceVerificationFailedError as exc:
                logger.warning("[rxc] Device verification failed: %s — won't retry.", exc)
                return  # Don't retry on auth failures

            except Exception as exc:
                logger.debug("[rxc] Hub not reachable (%s). Retrying in %.0fs.", exc, backoff)

            self._connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _connect(self) -> None:
        manifest = ProductManifest(id=PRODUCT_ID, version=PRODUCT_VERSION)
        client   = RexyCoreClient(manifest)

        # Register incoming message handlers
        @client.on_message(MSG_HELP_OFFER)
        async def _help_offer(envelope) -> None:
            logger.info("[rxc] RK AI is offering help.")
            if self._on_help_offer:
                await self._on_help_offer(envelope.payload)

        @client.on_message(MSG_HELP_DECLINE)
        async def _help_decline(envelope) -> None:
            logger.debug("[rxc] RK AI declined help request.")
            if self._on_help_decline:
                await self._on_help_decline(envelope.payload)

        @client.on_message(MSG_PONG)
        async def _pong(envelope) -> None:
            logger.debug("[rxc] RK AI pong received.")

        @client.on_message(MSG_SYSTEM_STATE_REQUEST)
        async def _system_state_request(envelope) -> None:
            logger.info("[rxc] Received system state request from %s", envelope.source)
            if self._on_system_state_request:
                payload = await self._on_system_state_request()
                if payload:
                    try:
                        await self._client.send(
                            target=envelope.source,
                            msg_type=MSG_SYSTEM_STATE_RESPONSE,
                            payload=payload,
                            metadata={"correlation_id": envelope.metadata.get("correlation_id", envelope.id)}
                        )
                        logger.debug("[rxc] Sent system state response to %s", envelope.source)
                    except Exception as e:
                        logger.error("[rxc] Failed to send system state response: %s", e)

        @client.on_connect
        async def _on_hub_connect() -> None:
            self._connected = True
            logger.info("[rxc] Connected to RexyCore Hub ✓")

        @client.on_disconnect
        async def _on_hub_disconnect() -> None:
            self._connected = False
            logger.info("[rxc] Disconnected from RexyCore Hub.")

        # connect() blocks until Hub ACKs registration or raises
        await client.connect()
        self._client = client

    # ── Legacy compat (old stub interface) ──────────────────────────────

    async def is_available(self) -> bool:
        """Alias for is_rk_ai_available() — kept for main.py compatibility."""
        return await self.is_rk_ai_available()

    async def send_context(
        self,
        context: Any,
        inference: Any,
        signals: list[str],
    ) -> bool:
        """Alias for send_stuck_context() — kept for main.py compatibility."""
        ctx_dict = context if isinstance(context, dict) else vars(context)
        inf_dict = inference if isinstance(inference, dict) else vars(inference)
        return await self.send_stuck_context(ctx_dict, inf_dict, signals)

    def update_endpoint(self, _endpoint: str) -> None:
        """No-op — endpoint comes from ~/.rexycore/config.json, not settings."""
        pass
