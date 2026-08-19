from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ResourceInfo(BaseModel):
    cpu_percent:      float
    ram_percent:      float
    ram_available_gb: float
    battery_percent:  Optional[float] = None
    battery_plugged:  Optional[bool]  = None
    load_tier:        Literal["LOW", "MEDIUM", "HIGH"]


class AppInfo(BaseModel):
    name:       str
    window_title: Optional[str] = None
    bundle_id:  Optional[str] = None


class PerceptionData(BaseModel):
    timestamp:       str = Field(default_factory=lambda: datetime.now().isoformat())
    # App
    active_app:      Optional[str] = None
    window_title:    Optional[str] = None
    # Screen
    screen_text:     Optional[str] = None
    # Vision (Phase 2)
    vision_summary:  Optional[str] = None
    # Clipboard
    clipboard_text:  Optional[str] = None
    # Resources
    cpu_percent:     float = 0.0
    ram_percent:     float = 0.0
    ram_available_gb:float = 0.0
    battery_percent: Optional[float] = None
    battery_plugged: Optional[bool]  = None
    load_tier:       Literal["LOW", "MEDIUM", "HIGH"] = "LOW"

    def to_ws_dict(self) -> dict:
        return self.model_dump()


class ContextState(BaseModel):
    activity:   str               # Coding, Debugging, Browsing …
    confidence: float             # 0.0 – 1.0
    app:        Optional[str] = None
    detail:     Optional[str] = None


class InferenceState(BaseModel):
    workflow:               str               # Active Development, Stuck …
    confidence:             float
    signals:                List[str] = Field(default_factory=list)
    stuck:                  bool  = False
    stuck_duration_minutes: float = 0.0
    # Observer context — enriches observation generation
    stuck_app:              Optional[str] = None   # e.g. "Visual Studio Code"
    stuck_window:           Optional[str] = None   # e.g. "auth.py — my-project"
    error_hint:             Optional[str] = None   # first error line seen on screen


class Observation(BaseModel):
    message:   str
    type:      str        # activity | resource | stuck | focus | battery | habit | error_recall
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class Episode(BaseModel):
    id:                Optional[int] = None
    start_time:        str
    end_time:          Optional[str] = None
    dominant_context:  Optional[str] = None
    inferred_workflow: Optional[str] = None
    apps_used:         List[str]     = Field(default_factory=list)
    observations:      List[str]     = Field(default_factory=list)
