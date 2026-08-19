from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


DATA_DIR = Path.home() / ".neytreya"


class NeytreyadSettings(BaseSettings):
    # Perception
    blocked_apps: List[str] = Field(default_factory=list)
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
    capture_interval: int = 2           # seconds between perception ticks
    clipboard_enabled: bool = True
    watching_enabled: bool = True       # master pause — set False to stop all capture
    ocr_enabled: bool = True            # Tesseract screen reading (no GPU needed)

    # Vision / Ollama (Phase 2)
    vision_enabled: bool = False        # Ollama qwen3-vl — separate from OCR
    vision_model: str = "qwen3-vl:8b"
    ollama_url: str = "http://localhost:11434"

    # RK AI (Phase 3)
    rk_ai_enabled: bool = False
    rk_ai_endpoint: str = ""

    # Observation thresholds (Phase 2)
    stuck_threshold_minutes: int = 15
    max_observations_per_hour: int = 10

    # Audio Recall (Phase 3)
    audio_recall_enabled: bool = False  # starts audiocap + faster-whisper transcription

    class Config:
        env_file = ".env"
        extra    = "ignore"   # don't crash on Electron-only fields (is_logged_in, user_name, etc.)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> "NeytreyadSettings":
        settings_file = DATA_DIR / "settings.json"
        if settings_file.exists():
            try:
                raw = json.loads(settings_file.read_text())
                return cls(**raw)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings_file = DATA_DIR / "settings.json"
        # Read existing file first so we don't wipe Electron-written auth fields
        # (is_logged_in, user_email, user_name, user_slug, user_plan, auth_method)
        existing: dict = {}
        if settings_file.exists():
            try:
                existing = json.loads(settings_file.read_text())
            except Exception:
                pass
        # Merge: existing fields win for keys we don't own; our fields override ours
        merged = {**existing, **self.model_dump()}
        settings_file.write_text(json.dumps(merged, indent=2))

    def is_quiet_time(self) -> bool:
        """Return True if current time falls within quiet hours."""
        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        start = self.quiet_hours_start
        end = self.quiet_hours_end
        if start <= end:
            return start <= now < end
        # Crosses midnight
        return now >= start or now < end

    def is_app_blocked(self, app_name: str) -> bool:
        return any(b.lower() in app_name.lower() for b in self.blocked_apps)
