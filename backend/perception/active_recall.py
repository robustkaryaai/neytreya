"""
perception/active_recall.py
────────────────────────────
Periodic visual memory capture.

- Every 1 minute  → compressed WebP thumbnail (~20-40 KB) saved to disk
- Every 5 minutes → Qwen VL vision summary generated and stored in DB

Storage budget: ~2-3 MB/hour, auto-pruned after 7 days.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RECALL_DIR = Path.home() / ".neytreya" / "recall"
WEBP_QUALITY = 25
THUMB_WIDTH = 900
KEEP_DAYS = 7

try:
    import mss
    from PIL import Image as PILImage
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("[recall] mss/PIL not available — recall snapshots disabled")


class ActiveRecall:
    def __init__(self) -> None:
        RECALL_DIR.mkdir(parents=True, exist_ok=True)
        self._last_capture_ts: float = 0.0

    def take_snapshot(self, app_name: str = "", window_title: str = "") -> Optional[str]:
        """Capture screen and save a compressed WebP thumbnail. Returns path or None."""
        if not _AVAILABLE:
            return None
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                raw = sct.grab(monitor)
                img = PILImage.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            if img.width > THUMB_WIDTH:
                ratio = THUMB_WIDTH / img.width
                new_h = int(img.height * ratio)
                img = img.resize((THUMB_WIDTH, new_h), PILImage.LANCZOS)

            now = datetime.now()
            safe_app = (app_name or "Unknown").replace("/", "_")[:20]
            filename = now.strftime(f"%Y-%m-%d_%H-%M-%S") + f"_{safe_app}.webp"
            filepath = RECALL_DIR / filename
            img.save(str(filepath), "WEBP", quality=WEBP_QUALITY, method=6)
            self._last_capture_ts = time.monotonic()
            logger.debug("[recall] Snapshot saved: %s (%.1f KB)", filename, filepath.stat().st_size / 1024)
            return filename
        except Exception as exc:
            logger.warning("[recall] Snapshot failed: %s", exc)
            return None

    def prune_old_snapshots(self) -> int:
        """Delete recall images older than KEEP_DAYS. Returns number pruned."""
        cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
        pruned = 0
        try:
            for f in RECALL_DIR.glob("*.webp"):
                try:
                    date_str = f.stem[:10]
                    fdate = datetime.strptime(date_str, "%Y-%m-%d")
                    if fdate < cutoff:
                        f.unlink()
                        pruned += 1
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("[recall] Pruning failed: %s", exc)
        if pruned:
            logger.info("[recall] Pruned %d old snapshots", pruned)
        return pruned

    def get_snapshots_for_date(self, date: str) -> list[dict]:
        """Return snapshots for a specific date (YYYY-MM-DD)."""
        results = []
        try:
            for f in sorted(RECALL_DIR.glob(f"{date}_*.webp")):
                try:
                    time_str = f.stem[11:19].replace("-", ":")
                    results.append({
                        "path": str(f),
                        "filename": f.name,
                        "time": time_str,
                        "size_kb": round(f.stat().st_size / 1024, 1),
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return results

    def get_today_snapshots(self) -> list[dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.get_snapshots_for_date(today)
