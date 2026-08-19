from __future__ import annotations

import logging
import re
from typing import Optional

from memory.models import ContextState, PerceptionData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule tables
# ---------------------------------------------------------------------------

_APP_MAP: dict[str, str] = {
    "VS Code": "Coding", "Code": "Coding", "Cursor": "Coding",
    "PyCharm": "Coding", "IntelliJ IDEA": "Coding", "WebStorm": "Coding",
    "Xcode": "Coding", "Sublime Text": "Coding", "Vim": "Coding",
    "Neovim": "Coding", "Emacs": "Coding", "Zed": "Coding",
    "Terminal": "Coding", "iTerm2": "Coding", "Warp": "Coding",
    "Hyper": "Coding", "kitty": "Coding", "Ghostty": "Coding",
    "Android Studio": "Coding", "Fleet": "Coding", "RustRover": "Coding",
    "DataGrip": "Coding", "CLion": "Coding", "GoLand": "Coding",
    "cmd": "Coding", "powershell": "Coding", "WindowsTerminal": "Coding",
    "Safari": "Browsing", "Google Chrome": "Browsing", "Firefox": "Browsing",
    "Arc": "Browsing", "Microsoft Edge": "Browsing", "Brave Browser": "Browsing",
    "Opera": "Browsing", "msedge": "Browsing", "chrome": "Browsing",
    "Figma": "Designing", "Sketch": "Designing", "Adobe XD": "Designing",
    "Photoshop": "Designing", "Illustrator": "Designing", "Canva": "Designing",
    "Framer": "Designing", "Penpot": "Designing",
    "Microsoft Word": "Writing", "Pages": "Writing",
    "Obsidian": "Writing", "Typora": "Writing", "Bear": "Writing",
    "Ulysses": "Writing", "iA Writer": "Writing", "Craft": "Writing",
    "Microsoft Excel": "Spreadsheets", "Numbers": "Spreadsheets",
    "Microsoft PowerPoint": "Slides", "Keynote": "Slides",
    "zoom": "Meeting", "Zoom": "Meeting", "Microsoft Teams": "Meeting",
    "Slack": "Messaging", "Discord": "Messaging", "Google Meet": "Meeting",
    "Loom": "Recording", "WhatsApp": "Messaging", "Messages": "Messaging",
    "Telegram": "Messaging", "Signal": "Messaging",
    "Preview": "Reading", "Kindle": "Reading", "Books": "Reading",
    "Spotify": "Listening to Music", "Music": "Listening to Music",
    "Apple Podcasts": "Listening to Podcast", "VLC": "Watching Video",
    "QuickTime Player": "Watching Video", "IINA": "Watching Video",
    "Finder": "Managing Files", "System Settings": "Configuring macOS",
    "System Preferences": "Configuring macOS", "Activity Monitor": "Monitoring System",
    "explorer": "Managing Files", "Explorer": "Managing Files",
    "taskmgr": "Monitoring System", "control": "Configuring Windows",
    "VMware Fusion": "Running VM", "Parallels Desktop": "Running VM",
    "UTM": "Running VM", "VirtualBox": "Running VM",
    "VMware Workstation": "Running VM", "QEMU": "Running VM",
    "vmware": "Running VM",
    "Things 3": "Planning", "OmniFocus": "Planning", "Todoist": "Planning",
    "Linear": "Project Management", "Jira": "Project Management",
    "Trello": "Project Management", "Asana": "Project Management",
    "Notion": "Taking Notes",
    "Mail": "Email", "Mimestream": "Email", "Superhuman": "Email",
    "Microsoft Outlook": "Email", "Spark": "Email",
    "Electron": "Running App", "Antigravity": "Using Antigravity",
    "notepad": "Writing", "Notepad": "Writing",
    "mspaint": "Designing", "Paint": "Designing",
}

_TITLE_ACTIVITY_MAP: list[tuple[str, str]] = [
    ("installing windows",    "Installing Windows"),
    ("windows setup",         "Installing Windows"),
    ("vmware",                "Running VM"),
    ("virtualbox",            "Running VM"),
    ("parallels",             "Running VM"),
    ("pull request",          "Code Review"),
    ("merge request",         "Code Review"),
    ("github.com",            "On GitHub"),
    ("gitlab.com",            "On GitLab"),
    ("vercel",                "Deploying"),
    ("netlify",               "Deploying"),
    ("railway",               "Deploying"),
    ("render.com",            "Deploying"),
    ("heroku",                "Deploying"),
    ("aws console",           "Cloud Dashboard"),
    ("google cloud",          "Cloud Dashboard"),
    ("azure",                 "Cloud Dashboard"),
    ("tableplus",             "Database Work"),
    ("postico",               "Database Work"),
    ("sequel pro",            "Database Work"),
    ("pgadmin",               "Database Work"),
    ("google meet",           "Video Call"),
    ("zoom meeting",          "Video Call"),
    ("teams meeting",         "Video Call"),
    ("spotify",               "Listening to Music"),
    ("youtube",               "Watching YouTube"),
    ("netflix",               "Watching Netflix"),
    ("twitch",                "Watching Twitch"),
    ("wikipedia",             "Reading Wikipedia"),
    ("medium.com",            "Reading Article"),
    ("notion.so",             "Taking Notes"),
    ("twitter.com",           "On Twitter / X"),
    ("x.com",                 "On Twitter / X"),
    ("reddit.com",            "On Reddit"),
    ("instagram",             "On Instagram"),
    ("facebook.com",          "On Facebook"),
    ("linkedin.com",          "On LinkedIn"),
    ("amazon.com",            "Shopping"),
    ("flipkart",              "Shopping"),
    ("gmail",                 "Email"),
    ("calendar",              "Calendar"),
    ("chatgpt",               "Using ChatGPT"),
    ("claude.ai",             "Using Claude"),
    ("gemini",                "Using Gemini"),
    ("copilot",               "Using Copilot"),
    ("perplexity",            "Researching with AI"),
    ("stackoverflow",         "Debugging on StackOverflow"),
    ("mdn web docs",          "Reading MDN Docs"),
    ("documentation",         "Reading Docs"),
    ("figma",                 "Designing in Figma"),
    ("google maps",           "Checking Maps"),
]

_KEYWORD_BOOSTS: dict[str, list[str]] = {
    "Debugging": [
        "traceback", "exception", "error:", "typeerror", "valueerror",
        "attributeerror", "nameerror", "keyerror", "indexerror",
        "syntaxerror", "assertion", "failed", "undefined", "null",
        "stacktrace", "at line", "line 0x",
    ],
    "Researching": [
        "stackoverflow.com", "github.com", "docs.", "documentation",
        "how to", "tutorial", "article", "medium.com", "devdocs",
        "mdn web docs", "pypi.org", "npmjs.com", "crates.io",
    ],
    "Studying": [
        "lecture", "chapter", "lesson", "quiz", "assignment", "course",
        "coursera", "udemy", "khan academy", "mit ocw",
    ],
}

_DEBUG_TITLE_KEYS = ["debug", "error", "traceback", "exception", "failed"]


class ContextEngine:
    """
    Three-layer precision: app map → window title patterns → smart fallback.
    'Working' is the true last resort only when nothing can be inferred.
    """

    def classify(self, perception: PerceptionData) -> ContextState:
        app         = perception.active_app or ""
        title       = perception.window_title or ""
        title_lower = title.lower()
        text        = (perception.screen_text or "").lower()

        base_activity = self._app_to_activity(app)
        confidence    = 0.55 if base_activity != "Idle" else 0.3

        # Window title precision override
        title_activity: Optional[str] = None
        for pattern, label in _TITLE_ACTIVITY_MAP:
            if pattern in title_lower:
                title_activity = label
                confidence = 0.88
                break

        # Keyword boosts from OCR text
        best_boost_activity: Optional[str] = None
        best_boost_score: float = 0.0
        for activity, keywords in _KEYWORD_BOOSTS.items():
            score = sum(1 for kw in keywords if kw in text or kw in title_lower)
            if score > best_boost_score:
                best_boost_score    = score
                best_boost_activity = activity

        debug_in_title = any(kw in title_lower for kw in _DEBUG_TITLE_KEYS)

        if debug_in_title:
            activity   = "Debugging"
            confidence = min(0.95, confidence + 0.3)
        elif title_activity:
            activity = title_activity
        elif best_boost_activity and best_boost_score >= 2:
            activity   = best_boost_activity
            confidence = min(0.90, confidence + 0.15 * best_boost_score)
        elif best_boost_activity and best_boost_score == 1:
            activity   = best_boost_activity if base_activity == "Browsing" else base_activity
            confidence = min(0.80, confidence + 0.08)
        else:
            smart    = self._smart_activity(base_activity, app, title)
            activity = smart if smart else base_activity

        detail = self._make_detail(app, perception.window_title)

        return ContextState(
            activity=activity,
            confidence=round(confidence, 2),
            app=app or None,
            detail=detail,
        )

    @staticmethod
    def _app_to_activity(app: str) -> str:
        if not app:
            return "Idle"
        if app in _APP_MAP:
            return _APP_MAP[app]
        app_lower = app.lower()
        for key, activity in _APP_MAP.items():
            if key.lower() in app_lower:
                return activity
        return "Working"

    @staticmethod
    def _smart_activity(base: str, app: str, title: str) -> Optional[str]:
        """Derive human-readable activity from window title when category is generic."""
        if not title:
            return None
        t = title.strip()

        # VM apps
        if any(kw in app.lower() for kw in ["vmware", "virtualbox", "parallels", "utm", "qemu"]):
            clean = re.sub(
                r'(VMware Fusion|VMware Workstation|VirtualBox|Parallels Desktop|UTM|QEMU)\s*[-\u2013|]*\s*',
                '', t, flags=re.I
            ).strip()
            return f"VM: {clean[:45]}" if clean else "Running VM"

        # Terminal running a command
        if any(kw in app.lower() for kw in ["terminal", "iterm", "warp", "kitty", "ghostty", "cmd", "powershell", "hyper"]):
            m = re.search(r'(?:\u2014|-|»|:)\s*(.+)$', t)
            cmd = (m.group(1).strip() if m else t)
            if cmd and len(cmd) > 2:
                return f"Running: {cmd[:45]}"

        # Browser — use the page title
        if base == "Browsing" and t:
            clean = re.sub(
                r'\s*[\u2013\-|·]\s*(Google Chrome|Firefox|Safari|Arc|Microsoft Edge|Brave).*$',
                '', t, flags=re.I
            ).strip()
            if clean and len(clean) > 3:
                return f"Browsing: {clean[:50]}"

        return None

    @staticmethod
    def _make_detail(app: str, window_title: Optional[str]) -> Optional[str]:
        if not window_title:
            return app or None
        title = window_title
        for suffix in [f" \u2014 {app}", f" - {app}", f" \u00b7 {app}", f"({app})"]:
            title = title.replace(suffix, "")
        return title.strip() or None
