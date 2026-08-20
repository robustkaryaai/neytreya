from __future__ import annotations

import logging
import subprocess
import sys
import time
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_IS_MAC     = sys.platform == "darwin"

# ── Windows-only: ctypes for GetForegroundWindow ──────────────────────────
if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes

    _user32 = ctypes.windll.user32

    def _get_foreground_hwnd():
        return _user32.GetForegroundWindow()

    def _get_foreground_pid() -> int:
        hwnd = _get_foreground_hwnd()
        if not hwnd:
            return 0
        pid = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _get_window_title_win() -> str:
        hwnd = _get_foreground_hwnd()
        if not hwnd:
            return ""
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value


class AppWatcher:
    """
    Detects the active foreground application cross-platform.

    - macOS  : Uses AppleScript (System Events). Falls back to psutil.
    - Windows: Uses ctypes (user32.GetForegroundWindow) + psutil. Zero external deps.
    - Linux  : Falls back to psutil best-effort.
    """

    _cache: Optional[dict] = None
    _cache_ts: float = 0.0
    _cache_ttl: float = 1.0  # seconds

    _last_real_app: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_app(self) -> dict:
        """
        Return {'name': str, 'window_title': str | None, 'bundle_id': str | None}.
        Result is cached for _cache_ttl seconds.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self._cache_ttl:
            return self._cache

        if _IS_WINDOWS:
            result = self._get_via_windows()
        elif _IS_MAC:
            result = self._get_via_osascript()
            if result is None:
                result = self._get_via_psutil()
        else:
            result = self._get_via_psutil()

        if result is None:
            result = self._get_via_psutil()

        # If the detected app is Neytreya itself, use the last real app the user was on.
        if result:
            app_name = result.get("name", "").lower()
            if app_name.endswith('.app'): app_name = app_name[:-4]
            if app_name.endswith('.exe'): app_name = app_name[:-4]
            
            # Self-filter: Neytreya/Electron panel + Windows shell chrome (taskbar, tray)
            _self_names = {"electron", "neytreya", "explorer", "shellexperiencehost",
                          "searchhost", "startmenuexperiencehost", "textinputhost"}
            
            if app_name in _self_names and self._last_real_app:
                result = self._last_real_app
            elif app_name not in _self_names:
                self._last_real_app = result

        self._cache = result
        self._cache_ts = now
        return result

    def get_all_running_apps(self) -> list[str]:
        """Return names of all user-visible running processes."""
        names: list[str] = []
        try:
            for proc in psutil.process_iter(["name", "status"]):
                try:
                    if proc.info["status"] == psutil.STATUS_RUNNING:
                        names.append(proc.info["name"] or "")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as exc:
            logger.warning("get_all_running_apps error: %s", exc)
        return names

    # ------------------------------------------------------------------
    # Windows native (ctypes / Win32 API)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_via_windows() -> Optional[dict]:
        """Use Win32 API to get the foreground window and its owning process name."""
        if not _IS_WINDOWS:
            return None
        try:
            window_title = _get_window_title_win() or None
            pid = _get_foreground_pid()
            if not pid:
                return None
            proc = psutil.Process(pid)
            app_name = proc.name()
            # Strip .exe for cleaner display
            if app_name.lower().endswith(".exe"):
                app_name = app_name[:-4]
            return {
                "name": app_name,
                "window_title": window_title,
                "bundle_id": None,
            }
        except Exception as exc:
            logger.debug("Windows app detection error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # macOS AppleScript (System Events only — safe, never launches apps)
    # ------------------------------------------------------------------

    @staticmethod
    def _run_osascript(script: str) -> str:
        """Run an AppleScript snippet and return stdout (stripped)."""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()

    def _get_via_osascript(self) -> Optional[dict]:
        try:
            app_name = self._run_osascript(
                'tell application "System Events" to get name of '
                "first application process whose frontmost is true"
            )
            if not app_name:
                return None

            window_title: Optional[str] = None
            try:
                window_title = self._run_osascript(
                    'tell application "System Events" to get name of front window '
                    f'of (first application process whose name is "{app_name}")'
                ) or None
            except Exception:
                pass

            return {
                "name": app_name,
                "window_title": window_title,
                "bundle_id": None,
            }
        except subprocess.TimeoutExpired:
            logger.debug("osascript timed out")
            return None
        except Exception as exc:
            logger.debug("osascript error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Universal psutil fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _get_via_psutil() -> dict:
        """Best-effort fallback: find the process with the highest CPU."""
        try:
            procs = [
                p
                for p in psutil.process_iter(["name", "cpu_percent"])
                if p.info["name"]
            ]
            if procs:
                top = max(procs, key=lambda p: p.info["cpu_percent"] or 0)
                return {"name": top.info["name"], "window_title": None, "bundle_id": None}
        except Exception as exc:
            logger.warning("psutil fallback error: %s", exc)
        return {"name": "Unknown", "window_title": None, "bundle_id": None}


