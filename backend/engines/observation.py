from __future__ import annotations

import logging
import re
import time
from typing import Optional, TYPE_CHECKING

from memory.models import ContextState, InferenceState, Observation, PerceptionData

if TYPE_CHECKING:
    from memory.db import NeytreyadDB

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cooldowns — minimum seconds between same observation type being shown again
# ---------------------------------------------------------------------------
_COOLDOWNS: dict[str, float] = {
    "activity":     8  * 60,    # 8 min between activity observations
    "stuck":        4  * 60,    # 4 min between stuck observations (reduced from 5)
    "resource":     10 * 60,    # 10 min between resource warnings
    "battery":      5  * 60,
    "focus":        12 * 60,
    "habit":        15 * 60,
    "error_recall": 10 * 60,    # 10 min between "seen this before" messages
}

# Resource thresholds
_CPU_WARN   = 80.0
_RAM_WARN   = 85.0
_BATT_LOW   = 20.0
_BATT_CRIT  = 10.0

# ── App-specific stuck message templates ──────────────────────────────────────
# Format: { app_keyword: { with_error: str, no_error: str } }
_APP_STUCK_TEMPLATES: dict[str, dict[str, str]] = {
    "visual studio code": {
        "with_error": "Been in VS Code on '{window}' for {dur} min — looks like there's an error still on screen.",
        "no_error":   "You've been in VS Code on '{window}' for {dur} min. Feeling stuck?",
    },
    "code": {  # fallback for VS Code process name
        "with_error": "Been in VS Code on '{window}' for {dur} min — looks like there's an error still on screen.",
        "no_error":   "You've been in VS Code on '{window}' for {dur} min. Feeling stuck?",
    },
    "cursor": {
        "with_error": "Been in Cursor on '{window}' for {dur} min — error still visible.",
        "no_error":   "You've been in Cursor on '{window}' for {dur} min. Still at the same spot?",
    },
    "xcode": {
        "with_error": "Xcode, '{window}', {dur} min in — the build error's still there.",
        "no_error":   "You've been in Xcode on '{window}' for {dur} min.",
    },
    "intellij idea": {
        "with_error": "IntelliJ, same file '{window}' for {dur} min — error's still visible.",
        "no_error":   "You've been in IntelliJ on '{window}' for {dur} min.",
    },
    "pycharm": {
        "with_error": "PyCharm, same file for {dur} min — error's still on screen.",
        "no_error":   "You've been in PyCharm for {dur} min without switching.",
    },
    "terminal": {
        "with_error": "Terminal's been running the same thing for {dur} min — last output had errors.",
        "no_error":   "You've had the terminal open for {dur} min. Still waiting on something?",
    },
    "iterm2": {
        "with_error": "iTerm has been on the same output for {dur} min — errors visible.",
        "no_error":   "You've been in iTerm for {dur} min without switching.",
    },
    "warp": {
        "with_error": "Warp, same command output for {dur} min — errors in there.",
        "no_error":   "You've been in Warp for {dur} min. Still debugging that command?",
    },
    "chrome": {
        "no_error": "You've had Chrome on '{window}' for {dur} min. Still looking for that answer?",
    },
    "safari": {
        "no_error": "You've had the same Safari tab open for {dur} min. Still reading?",
    },
    "figma": {
        "no_error": "You've been in Figma on '{window}' for {dur} min. Stuck on that design?",
    },
    "photoshop": {
        "no_error": "Photoshop, same document for {dur} min. Still working that layer?",
    },
    "notion": {
        "no_error": "You've been in Notion on '{window}' for {dur} min.",
    },
    "slack": {
        "no_error": "You've had Slack open for {dur} min. Waiting on a reply?",
    },
    "zoom": {
        "no_error": "You've been in a Zoom call for {dur} min.",
    },
}


def _app_key(app_name: str) -> Optional[str]:
    """Return the matched app template key or None."""
    lower = (app_name or "").lower()
    for key in _APP_STUCK_TEMPLATES:
        if key in lower:
            return key
    return None


def _clean_window(window_title: Optional[str]) -> str:
    """Shorten window title to the most useful part."""
    if not window_title:
        return ""
    # "auth.py — my-project — Visual Studio Code" → "auth.py"
    parts = re.split(r"\s[—–-]\s", window_title)
    return parts[0].strip()[:50] if parts else window_title[:50]


class ObservationEngine:
    """
    Converts inferences into short, specific, natural observations.

    Rules:
    - NEVER gives solutions or advice.
    - NEVER gives code, fixes, or explanations.
    - Only states what it sees (observations) — acts as a silent observer.
    - App-specific messages where possible.
    - Uses cooldowns to avoid spamming.
    - Max 2 observations per cycle.
    - Can reference the error recall DB to surface patterns.
    """

    def __init__(self, db: Optional["NeytreyadDB"] = None) -> None:
        self._last_shown: dict[str, float] = {}
        self._session_start = time.monotonic()
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        context:    ContextState,
        inference:  InferenceState,
        perception: PerceptionData,
    ) -> list[Observation]:

        now = time.monotonic()
        candidates: list[Observation] = []

        # 1. Stuck observation (highest priority) — context-rich
        if inference.stuck:
            if self._can_show("stuck", now):
                obs = self._context_rich_stuck_obs(inference, perception, now)
                if obs:
                    candidates.append(obs)

        # 2. Error recall — "seen this before?"
        if inference.error_hint and self._can_show("error_recall", now):
            obs = self._error_recall_obs_sync(inference, perception)
            if obs:
                candidates.append(obs)

        # 3. Activity / workflow observations (not stuck)
        if not inference.stuck and len(candidates) < 2:
            obs = self._activity_obs(context, inference, now)
            if obs:
                candidates.append(obs)

        # 4. Resource observations
        if len(candidates) < 2:
            res_obs = self._resource_obs(perception, now)
            if res_obs:
                candidates.append(res_obs)

        # Mark shown
        for obs in candidates[:2]:
            self._last_shown[obs.type] = now

        return candidates[:2]

    # ------------------------------------------------------------------
    # Context-rich stuck observation
    # ------------------------------------------------------------------

    def _context_rich_stuck_obs(
        self,
        inference:  InferenceState,
        perception: PerceptionData,
        now:        float,
    ) -> Optional[Observation]:
        dur = int(inference.stuck_duration_minutes) or 1
        app = inference.stuck_app or perception.active_app or ""
        win = _clean_window(inference.stuck_window or perception.window_title)
        has_error = bool(inference.error_hint)

        key = _app_key(app)

        if key and key in _APP_STUCK_TEMPLATES:
            tmpl_set = _APP_STUCK_TEMPLATES[key]
            if has_error and "with_error" in tmpl_set:
                tmpl = tmpl_set["with_error"]
            else:
                tmpl = tmpl_set.get("no_error", "")

            if tmpl:
                msg = tmpl.format(window=win or app, dur=dur, app=app)
                return self._make("stuck", msg)

        # Generic fallback (still better than before)
        if has_error:
            msg = (
                f"You've been on the same screen in {app or 'this app'} for {dur} min "
                f"— there's what looks like an error still visible."
            )
        elif dur >= 10:
            msg = f"You've been here for about {dur} minutes — still at the same place."
        else:
            msg = "Looks like you've been on this for a while."

        return self._make("stuck", msg)

    # ------------------------------------------------------------------
    # Error recall (synchronous best-effort)
    # ------------------------------------------------------------------

    def _error_recall_obs_sync(
        self,
        inference:  InferenceState,
        perception: PerceptionData,
    ) -> Optional[Observation]:
        """
        Check if this error was seen before. Synchronous wrapper — uses a cached
        result if the db hasn't been set.
        """
        if not self._db or not inference.error_hint:
            return None

        # We can't await here (sync context), so we use a fire-and-check pattern.
        # The async version is called from main.py perception tick instead.
        return None

    # ------------------------------------------------------------------
    # Async error recall — called from main.py
    # ------------------------------------------------------------------

    async def check_error_recall(
        self,
        inference:  InferenceState,
        perception: PerceptionData,
        now:        float,
    ) -> Optional[Observation]:
        """Async: check DB for a previously seen error and return an observation."""
        if not self._db or not inference.error_hint:
            return None
        if not self._can_show("error_recall", now):
            return None

        try:
            existing = await self._db.find_similar_error(inference.error_hint)
            if existing and existing.get("occurrence_count", 1) > 1:
                count = existing["occurrence_count"]
                app   = existing.get("app") or "another project"
                self._last_shown["error_recall"] = now
                return self._make(
                    "error_recall",
                    f"This error pattern looks familiar — you've seen it {count} times before"
                    + (f" in {app}." if app else "."),
                )
        except Exception as exc:
            logger.debug("Error recall check failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Activity observations
    # ------------------------------------------------------------------

    def _activity_obs(
        self,
        ctx:  ContextState,
        inf:  InferenceState,
        now:  float,
    ) -> Optional[Observation]:

        workflow = inf.workflow
        dur_min  = inf.stuck_duration_minutes

        templates: dict[str, list[tuple[float, str]]] = {
            "Debugging": [
                (30, "That's a solid debugging session — {dur} minutes in."),
                (15, "You've been debugging for about {dur} minutes."),
            ],
            "Deep Focus": [
                (60, "You're in a long deep focus session — {dur} minutes."),
                (25, "You're in a solid focus session."),
            ],
            "Context Switching": [
                (0, "Looks like you're jumping between a few things."),
            ],
            "Researching": [
                (0, "Looks like you're researching something."),
            ],
            "Active Development": [
                (45, "You've been coding for quite a while — {dur} minutes."),
                (20, "You've been coding for about {dur} minutes."),
            ],
            "Meeting": [
                (45, "Long meeting — about {dur} minutes in."),
                (20, "You've been in a meeting for about {dur} minutes."),
            ],
            "Studying": [
                (20, "Looks like you're in a study session."),
            ],
            "Writing": [
                (30, "You've been writing for about {dur} minutes."),
            ],
        }

        if workflow not in templates:
            return None
        if not self._can_show("activity", now) and not self._can_show("focus", now):
            return None

        session_min = (now - self._session_start) / 60.0
        dur         = int(max(session_min, dur_min))

        for min_dur, tmpl in templates[workflow]:
            if dur >= min_dur:
                msg  = tmpl.format(dur=dur)
                kind = "focus" if workflow == "Deep Focus" else "activity"
                if self._can_show(kind, now):
                    return self._make(kind, msg)

        return None

    # ------------------------------------------------------------------
    # Resource observations
    # ------------------------------------------------------------------

    def _resource_obs(
        self,
        perception: PerceptionData,
        now:        float,
    ) -> Optional[Observation]:

        # Battery critical
        batt = perception.battery_percent
        if batt is not None and not perception.battery_plugged:
            if batt <= _BATT_CRIT and self._can_show("battery", now):
                return self._make("battery", f"Battery is very low — {int(batt)}%.")
            if batt <= _BATT_LOW and self._can_show("battery", now):
                return self._make("battery", f"Battery is running low — {int(batt)}%.")

        # RAM
        if perception.ram_percent >= _RAM_WARN and self._can_show("resource", now):
            return self._make("resource", "Memory usage is getting high.")

        # CPU
        if perception.cpu_percent >= _CPU_WARN and self._can_show("resource", now):
            return self._make("resource", "System load is pretty high right now.")

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _can_show(self, obs_type: str, now: float) -> bool:
        cooldown = _COOLDOWNS.get(obs_type, 5 * 60)
        last     = self._last_shown.get(obs_type, 0.0)
        return (now - last) >= cooldown

    @staticmethod
    def _make(obs_type: str, message: str) -> Observation:
        from datetime import datetime
        return Observation(
            message=message,
            type=obs_type,
            timestamp=datetime.now().isoformat(),
        )
