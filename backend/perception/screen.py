from __future__ import annotations

import io
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import mss
    import mss.tools
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False
    logger.warning("mss not installed — screen capture disabled")

try:
    import pytesseract
    from PIL import Image
    # Verify the tesseract binary is actually on PATH (not just the Python wrapper)
    pytesseract.get_tesseract_version()
    _TESS_AVAILABLE = True
except Exception:
    _TESS_AVAILABLE = False
    logger.warning(
        "Tesseract not found — OCR disabled. "
        "Install with: brew install tesseract"
    )


# Max width we downscale to before passing to OCR (keeps CPU low)
_MAX_WIDTH = 1280
# Tesseract config: fast single-block OCR
_TESS_CONFIG = "--oem 3 --psm 6"


class ScreenWatcher:
    """
    Captures the primary monitor and extracts text via OCR.
    Gracefully degrades when mss / tesseract are unavailable.
    """

    def __init__(self, min_interval: float = 8.0) -> None:
        """
        min_interval: minimum seconds between captures (adaptive throttle).
        """
        self._min_interval = min_interval
        self._last_capture_ts: float = 0.0
        self._last_image: Optional["Image.Image"] = None
        self._last_text: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_screenshot(self) -> Optional["Image.Image"]:
        """Grab the primary monitor. Returns a PIL Image or None."""
        if not _MSS_AVAILABLE:
            return None

        from PIL import Image as PILImage

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                raw = sct.grab(monitor)
                img = PILImage.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            # Downscale if too wide
            if img.width > _MAX_WIDTH:
                ratio = _MAX_WIDTH / img.width
                new_h = int(img.height * ratio)
                img = img.resize((_MAX_WIDTH, new_h), PILImage.LANCZOS)

            self._last_image = img
            self._last_capture_ts = time.monotonic()
            return img
        except Exception as exc:
            logger.warning("Screenshot capture failed: %s", exc)
            return None

    def extract_text(self, image: Optional["Image.Image"] = None) -> str:
        """
        Run OCR on *image* (or the last captured image).
        Returns cleaned text string, empty on failure.
        """
        if not _TESS_AVAILABLE:
            return ""

        target = image or self._last_image
        if target is None:
            return ""

        try:
            raw = pytesseract.image_to_string(target, config=_TESS_CONFIG)
            # Strip excessive whitespace
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            text = "\n".join(lines)
            self._last_text = text
            return text
        except Exception as exc:
            logger.warning("OCR failed: %s", exc)
            return self._last_text  # return stale cache rather than empty

    def get_screen_data(self, force: bool = False) -> dict:
        """
        Returns {'image': PIL.Image | None, 'text': str, 'timestamp': float}.
        Skips capture if called too soon (respects min_interval) unless force=True.
        """
        now = time.monotonic()
        if not force and (now - self._last_capture_ts) < self._min_interval:
            # Return cached data
            return {
                "image": self._last_image,
                "text": self._last_text,
                "timestamp": self._last_capture_ts,
                "cached": True,
            }

        img = self.capture_screenshot()
        text = self.extract_text(img) if img is not None else ""
        return {
            "image": img,
            "text": text,
            "timestamp": self._last_capture_ts,
            "cached": False,
        }

    @property
    def is_available(self) -> bool:
        return _MSS_AVAILABLE
