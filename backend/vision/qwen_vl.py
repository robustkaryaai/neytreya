from __future__ import annotations

import base64
import io
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── qwen3-vl model tiers (VL-only, ordered best→lightest) ────────────────────
# Only qwen3-vl variants — no text-only fallbacks.
# Each tier has min_ram_gb of *available* RAM required to run it comfortably.
_QWEN3VL_TIERS = [
    {"model": "qwen3-vl:30b",  "min_ram_gb": 22.0, "label": "Qwen3-VL 30B"},
    {"model": "qwen3-vl:8b",   "min_ram_gb": 7.0,  "label": "Qwen3-VL 8B (recommended)"},
    {"model": "qwen3-vl:4b",   "min_ram_gb": 4.0,  "label": "Qwen3-VL 4B"},
    {"model": "qwen3-vl:2b",   "min_ram_gb": 0.0,  "label": "Qwen3-VL 2B"},
]

# Minimum seconds to wait between vision calls regardless of window changes
# (protects against rapid window-switching hammering Ollama)
_MIN_VISION_INTERVAL   = 300.0   # seconds
# If a window change is detected, override the interval and call sooner
_WINDOW_CHANGE_INTERVAL = 300.0   # seconds grace after a switch


def pick_tier_for_ram(available_ram_gb: float) -> str:
    """Return best qwen3-vl model name that fits in available RAM."""
    for tier in _QWEN3VL_TIERS:
        if available_ram_gb >= tier["min_ram_gb"]:
            return tier["model"]
    return _QWEN3VL_TIERS[-1]["model"]   # always at least 2b


class QwenVLVision:
    """
    Vision module powered exclusively by qwen3-vl via Ollama.

    Behaviour:
    - Runs when load_tier is LOW or MEDIUM (not HIGH)
    - Triggered on every window change (with a short debounce)
    - Falls back through qwen3-vl tier list based on available RAM
    - Sends the full screenshot (not downscaled for text, kept at 1280px for speed)
    - Passes rich context: active_app, window_title, screen_text, clipboard
    - Returns '' on any failure — never crashes the perception loop

    Model selection (auto, based on Ollama-installed models + available RAM):
        qwen3-vl:30b  →  qwen3-vl:8b  →  qwen3-vl:4b  →  qwen3-vl:2b
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "",   # empty = auto-pick from tiers
    ) -> None:
        self.ollama_url      = ollama_url.rstrip("/")
        self.preferred_model = model
        self._active_model:  Optional[str] = None
        self._last_call_ts:  float         = 0.0
        self._last_window:   str           = ""   # track window changes

    # ── Public API ──────────────────────────────────────────────────────

    async def analyze(
        self,
        image:        "PIL.Image.Image",  # type: ignore[name-defined]
        context_hint: str = "",
        *,
        # Rich context fields — all optional, all improve accuracy
        active_app:    str = "",
        window_title:  str = "",
        screen_text:   str = "",
        clipboard_text:str = "",
        ram_available_gb: float = 0.0,
        window_changed: bool = False,
    ) -> str:
        """
        Analyze a full screenshot with rich context.
        Returns a 3-5 sentence description of what's on screen and what the
        user is doing. Returns '' on failure or when throttled.
        """
        now = time.monotonic()
        elapsed = now - self._last_call_ts

        # Throttle: skip unless minimum interval passed, unless window changed
        min_interval = _WINDOW_CHANGE_INTERVAL if window_changed else _MIN_VISION_INTERVAL
        if elapsed < min_interval:
            return ""

        model = await self._get_active_model(ram_available_gb)
        if model is None:
            return ""

        try:
            img_b64 = self._image_to_b64(image)
            prompt  = self._build_prompt(
                active_app=active_app,
                window_title=window_title,
                screen_text=screen_text,
                clipboard_text=clipboard_text,
                context_hint=context_hint,
            )

            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model":  model,
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                        "options": {
                            "temperature":  0.1,
                            "num_predict":  250,
                            "num_ctx":      4096,
                        },
                    },
                )
                resp.raise_for_status()
                result = resp.json().get("response", "").strip()
                self._last_call_ts = time.monotonic()
                logger.debug("[vision] %s: %s…", model, result[:80])
                return result

        except httpx.TimeoutException:
            logger.warning("[vision] Call timed out (model: %s)", model)
        except Exception as exc:
            logger.debug("[vision] Call failed: %s", exc)

        return ""

    async def predict_category(self, app_name: str, window_title: str) -> str:
        """Ask Qwen VL what the user is doing — returns 1 to 3 words max."""
        model = await self._get_active_model(2.0)
        if not model:
            return ""

        prompt = (
            "SYSTEM: You are a precision activity classifier. "
            "You MUST reply with 1 to 3 words ONLY. No punctuation. No explanation. No extra text. "
            "Describe exactly what the user is doing right now in the most specific, natural way possible.\n\n"
            f"App: {app_name}\n"
            f"Window title: {window_title}\n\n"
            "Examples of good responses:\n"
            "  Installing Windows\n"
            "  Code Review GitHub\n"
            "  npm run dev\n"
            "  Watching YouTube\n"
            "  Reading MDN Docs\n"
            "  Writing unit tests\n"
            "  Designing in Figma\n"
            "  Using ChatGPT\n\n"
            "Your response (1-3 words only):"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model":  model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "num_predict": 12,   # hard cap — 1-3 words
                            "stop": ["\n", ".", ":"],
                        },
                    },
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "").strip()

                # Enforce max 3 words, strip stray punctuation
                words = raw.replace(",", "").replace(".", "").strip().split()
                if 1 <= len(words) <= 3:
                    return " ".join(w.capitalize() for w in words)
                # If model went rogue and gave more, take first 3 words
                if len(words) > 3:
                    return " ".join(w.capitalize() for w in words[:3])

        except Exception as exc:
            logger.debug("[vision] Category predict failed: %s", exc)

        return ""

    async def is_available(self) -> bool:
        """Check if Ollama is reachable and has at least one qwen3-vl model."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    installed = [m["name"] for m in resp.json().get("models", [])]
                    return any("qwen3-vl" in m for m in installed)
        except Exception:
            pass
        return False

    async def get_installed_models(self) -> list[str]:
        """Return names of all Ollama-installed models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.debug("Model list failed: %s", exc)
        return []

    async def get_best_available_model(self, ram_available_gb: float = 0.0) -> Optional[str]:
        """Return the best installed qwen3-vl model that fits in available RAM."""
        installed = set(await self.get_installed_models())

        # User-specified preferred model
        if self.preferred_model and self.preferred_model in installed:
            return self.preferred_model

        # Walk tiers: best fit for RAM first
        for tier in _QWEN3VL_TIERS:
            if tier["model"] in installed and ram_available_gb >= tier["min_ram_gb"]:
                return tier["model"]

        # Fallback: any installed qwen3-vl regardless of RAM
        for tier in _QWEN3VL_TIERS:
            if tier["model"] in installed:
                return tier["model"]

        return None

    def notify_window_changed(self, new_window: str) -> bool:
        """Call this when active window changes. Returns True if it changed."""
        if new_window and new_window != self._last_window:
            self._last_window = new_window
            return True
        return False

    # ── Internal ────────────────────────────────────────────────────────

    async def _get_active_model(self, ram_available_gb: float = 0.0) -> Optional[str]:
        # Re-check every time if not set, so RAM-based selection stays fresh
        if self._active_model:
            return self._active_model
        model = await self.get_best_available_model(ram_available_gb)
        if model:
            logger.info("[vision] Model selected: %s", model)
            self._active_model = model
        return model

    @staticmethod
    def _build_prompt(
        active_app:    str,
        window_title:  str,
        screen_text:   str,
        clipboard_text:str,
        context_hint:  str,
    ) -> str:
        lines = [
            "You are Neytreya, a silent local screen observer. Analyze this screenshot and provide a precise 3-5 sentence observation.",
            "Focus on: what the user is actively doing, what content/code/text is visible, any errors or warnings present, and which specific task appears to be in progress.",
            "Be factual, specific, and concise. Do NOT give advice. Do NOT start with 'I can see' — just describe directly.",
            "",
        ]
        if active_app:
            lines.append(f"Active application: {active_app}")
        if window_title:
            lines.append(f"Window title: {window_title}")
        if screen_text:
            # Limit screen text to avoid overwhelming the context
            truncated = screen_text[:800] if len(screen_text) > 800 else screen_text
            lines.append(f"Visible text on screen:\n{truncated}")
        if clipboard_text:
            lines.append(f"Clipboard: {clipboard_text[:200]}")
        if context_hint:
            lines.append(f"Additional context: {context_hint}")
        return "\n".join(lines)

    @staticmethod
    def _image_to_b64(image: "PIL.Image.Image") -> str:  # type: ignore[name-defined]
        """Encode screenshot to base64 JPEG. Higher quality for VL accuracy."""
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
