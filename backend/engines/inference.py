from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Set, Tuple

from memory.models import ContextState, InferenceState, PerceptionData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (all in seconds unless named _min / _count)
# ---------------------------------------------------------------------------
_HISTORY_WINDOW      = 30 * 60     # 30 min of history retained
_SAME_WINDOW_STUCK   = 15 * 60     # 15 min same window → high stuck signal (generic)
_SAME_WINDOW_STUCK_CODE = 8 * 60  # 8 min for coding apps → faster detection
_SAME_WINDOW_WARN    = 5  * 60     # 5 min → moderate signal
_SWITCH_WINDOW       = 2  * 60     # 2-min window for rapid switching
_RAPID_SWITCH_COUNT  = 5           # switches in _SWITCH_WINDOW → context-switching
_DEEP_FOCUS_MIN      = 25 * 60     # 25 min same context, active → deep focus
_IDLE_MIN            = 5  * 60     # 5 min no meaningful change → idle

# Coding/dev apps get faster stuck detection (8 min vs 15 min)
_CODING_APPS: Set[str] = {
    "visual studio code", "code", "xcode", "intellij idea", "pycharm",
    "webstorm", "clion", "goland", "android studio", "vim", "nvim",
    "neovim", "emacs", "sublime text", "atom", "cursor", "zed",
}

# Terminal apps — medium threshold (10 min)
_TERMINAL_APPS: Set[str] = {
    "terminal", "iterm2", "iterm", "warp", "ghostty", "kitty", "alacritty",
    "hyper", "windows terminal", "cmd", "powershell",
}

_ERROR_KEYWORDS = [
    "error", "exception", "traceback", "failed", "undefined",
    "typeerror", "valueerror", "syntaxerror", "nameerror",
    "assertion", "null", "panic", "fatal", "cannot", "cannot find",
    "module not found", "segfault", "segmentation fault",
]


@dataclass
class _Snapshot:
    ts:           float
    app:          Optional[str]
    window_title: Optional[str]
    activity:     str
    screen_text:  Optional[str]


class StuckDetector:
    """
    Tracks window stability and error patterns to score 'stuck' confidence.
    Now also returns the app name, window title, and first error line for
    context-rich observer messages.
    """

    def __init__(self) -> None:
        self._window_history: Deque[Tuple[str, float]] = deque()
        self._app_switches:   Deque[float]             = deque()
        self._last_app: Optional[str]                  = None

    def update(
        self,
        perception: PerceptionData,
        stuck_threshold_sec: float = _SAME_WINDOW_STUCK,
    ) -> Tuple[float, list[str], float, Optional[str], Optional[str], Optional[str]]:
        """
        Returns:
            (confidence, signals, duration_minutes, stuck_app, stuck_window, error_hint)
        """
        now   = time.monotonic()
        title = perception.window_title or perception.active_app or ""
        text  = (perception.screen_text or "").lower()

        # Dynamically choose threshold based on app type
        app_lower = (perception.active_app or "").lower()
        if any(a in app_lower for a in _CODING_APPS):
            effective_threshold = _SAME_WINDOW_STUCK_CODE
        elif any(a in app_lower for a in _TERMINAL_APPS):
            effective_threshold = 10 * 60
        else:
            effective_threshold = stuck_threshold_sec

        # Maintain window history
        self._window_history.append((title, now))
        cutoff = now - _HISTORY_WINDOW
        while self._window_history and self._window_history[0][1] < cutoff:
            self._window_history.popleft()

        # Track app switches
        if perception.active_app != self._last_app:
            self._app_switches.append(now)
            self._last_app = perception.active_app
        switch_cutoff = now - _SWITCH_WINDOW
        while self._app_switches and self._app_switches[0] < switch_cutoff:
            self._app_switches.popleft()

        confidence = 0.0
        signals: list[str] = []
        duration_min = 0.0
        error_hint: Optional[str] = None

        # Signal 1: Same window title held for a long time
        if self._window_history:
            same_since = self._first_different_ts(title)
            held_sec   = now - same_since
            duration_min = held_sec / 60.0

            if held_sec >= effective_threshold:
                confidence += 0.45
                signals.append(f"Same window for {int(held_sec // 60)} min")
            elif held_sec >= _SAME_WINDOW_WARN:
                confidence += 0.20
                signals.append(f"Staying in same view ({int(held_sec // 60)} min)")

        # Signal 2: Error keywords in OCR text
        error_hits = sum(1 for kw in _ERROR_KEYWORDS if kw in text)
        if error_hits >= 3:
            confidence += 0.35
            signals.append("Multiple error patterns on screen")
        elif error_hits >= 1:
            confidence += 0.15
            signals.append("Error pattern detected")

        # Extract first error line as hint
        if error_hits >= 1 and perception.screen_text:
            for line in perception.screen_text.splitlines():
                ll = line.lower().strip()
                if any(kw in ll for kw in _ERROR_KEYWORDS) and len(ll) > 5:
                    error_hint = line.strip()[:120]
                    break

        # Signal 3: Rapid app switching
        if len(self._app_switches) >= _RAPID_SWITCH_COUNT:
            confidence += 0.20
            signals.append(f"Switching apps rapidly ({len(self._app_switches)}x in 2 min)")

        return (
            min(confidence, 1.0),
            signals,
            duration_min,
            perception.active_app,
            perception.window_title,
            error_hint,
        )

    def _first_different_ts(self, current_title: str) -> float:
        """Return timestamp when the current title first appeared in a continuous run."""
        for title, ts in reversed(self._window_history):
            if title != current_title:
                return ts
        return self._window_history[0][1] if self._window_history else time.monotonic()


class InferenceEngine:
    """
    Inference Engine: ContextState + PerceptionData → InferenceState.

    Infers workflow states using rule-based confidence scoring.
    Stuck detection lives here. Purely local — no LLM.
    Now surfaces stuck_app, stuck_window, error_hint for context-rich observations.
    """

    def __init__(self, stuck_threshold_minutes: int = 15) -> None:
        self._history: Deque[_Snapshot] = deque()
        self._stuck  = StuckDetector()
        self._stuck_threshold_sec = stuck_threshold_minutes * 60

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def infer(self, context: ContextState, perception: PerceptionData) -> InferenceState:
        now = time.monotonic()

        # Store snapshot
        snap = _Snapshot(
            ts           = now,
            app          = perception.active_app,
            window_title = perception.window_title,
            activity     = context.activity,
            screen_text  = perception.screen_text,
        )
        self._history.append(snap)

        # Trim old history
        cutoff = now - _HISTORY_WINDOW
        while self._history and self._history[0].ts < cutoff:
            self._history.popleft()

        # Run stuck detection
        stuck_conf, stuck_signals, stuck_dur_min, stuck_app, stuck_window, error_hint = (
            self._stuck.update(perception, self._stuck_threshold_sec)
        )

        # Infer workflow
        workflow, wf_confidence, wf_signals = self._infer_workflow(
            context, perception, stuck_conf, stuck_signals
        )

        stuck = stuck_conf >= 0.6

        return InferenceState(
            workflow=workflow,
            confidence=round(wf_confidence, 2),
            signals=wf_signals,
            stuck=stuck,
            stuck_duration_minutes=round(stuck_dur_min, 1),
            stuck_app=stuck_app if stuck else None,
            stuck_window=stuck_window if stuck else None,
            error_hint=error_hint if stuck else None,
        )

    # ------------------------------------------------------------------
    # Workflow inference
    # ------------------------------------------------------------------

    def _infer_workflow(
        self,
        ctx:         ContextState,
        perception:  PerceptionData,
        stuck_conf:  float,
        stuck_signals: list[str],
    ) -> Tuple[str, float, list[str]]:

        activity = ctx.activity
        signals: list[str] = list(stuck_signals)
        confidence = ctx.confidence

        # ── Stuck (highest priority)
        if stuck_conf >= 0.6:
            return "Stuck", min(0.90, stuck_conf), signals

        # ── Idle
        if activity == "Idle" or not perception.active_app:
            return "Idle", 0.85, signals

        # ── Rapid context switching
        unique_apps = self._recent_apps(120)
        if len(unique_apps) >= 4:
            signals.append(f"{len(unique_apps)} apps in last 2 min")
            return "Context Switching", min(0.85, 0.55 + len(unique_apps) * 0.06), signals

        # ── Debugging
        if activity == "Debugging":
            return "Debugging", min(0.90, confidence + 0.1), signals

        # ── Deep Focus
        focus_duration = self._continuous_activity_duration(activity)
        if focus_duration >= _DEEP_FOCUS_MIN and len(unique_apps) <= 2:
            signals.append(f"Focused for {int(focus_duration // 60)} min")
            return "Deep Focus", 0.82, signals

        # ── Moderate stuck (light signal)
        if stuck_conf >= 0.3:
            signals.append("Possible slow progress")
            return "Debugging" if activity == "Coding" else activity, confidence, signals

        # ── Activity-based fallback mapping
        workflow_map = {
            "Coding":      "Active Development",
            "Researching": "Researching",
            "Browsing":    "Browsing",
            "Writing":     "Writing",
            "Designing":   "Designing",
            "Studying":    "Studying",
            "Meeting":     "Meeting",
        }
        return workflow_map.get(activity, activity), confidence, signals

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    def _recent_activities(self, seconds: float) -> list[str]:
        cutoff = time.monotonic() - seconds
        return [s.activity for s in self._history if s.ts >= cutoff]

    def _recent_apps(self, seconds: float) -> set[str]:
        cutoff = time.monotonic() - seconds
        return {s.app for s in self._history if s.ts >= cutoff and s.app}

    def _continuous_activity_duration(self, activity: str) -> float:
        """How long the given activity has been continuous (uninterrupted) in seconds."""
        now = time.monotonic()
        duration = 0.0
        prev_ts = now
        for snap in reversed(self._history):
            if snap.activity != activity:
                break
            duration = prev_ts - snap.ts
            prev_ts  = snap.ts
        return duration + (now - prev_ts) if duration > 0 else 0.0
