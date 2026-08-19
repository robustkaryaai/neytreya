from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pyperclip
    _CLIP_AVAILABLE = True
except ImportError:
    _CLIP_AVAILABLE = False
    logger.warning("pyperclip not installed — clipboard monitoring disabled")

_MAX_CHARS = 500  # truncate clipboard content for privacy


class ClipboardWatcher:
    """
    Optionally monitors the system clipboard.
    Only reports content that has changed since last poll.
    """

    def __init__(self) -> None:
        self._last: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_clipboard(self) -> Optional[str]:
        """Return current clipboard content (up to _MAX_CHARS), or None on error."""
        if not _CLIP_AVAILABLE:
            return None
        try:
            text = pyperclip.paste()
            if isinstance(text, str) and text.strip():
                return text[:_MAX_CHARS]
        except Exception as exc:
            logger.debug("Clipboard read error: %s", exc)
        return None

    def has_changed(self) -> bool:
        """True if clipboard content differs from the last polled value."""
        current = self.get_clipboard()
        return current != self._last

    def get_if_changed(self) -> Optional[str]:
        """
        Return clipboard text only if it changed since the last call.
        Updates the internal cache after reading.
        """
        current = self.get_clipboard()
        if current != self._last:
            self._last = current
            return current
        return None

    @property
    def is_available(self) -> bool:
        return _CLIP_AVAILABLE
