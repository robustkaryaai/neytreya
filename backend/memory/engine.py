"""
memory/engine.py
─────────────────
Memory Engine — extracts memorable entities from each perception tick
and writes them into the local timeline.

What it records:
  - Every perception tick → timeline row
  - Projects extracted from window titles
  - Websites extracted from browser window titles
  - Documents/files extracted from window titles
  - Errors extracted from screen text

What it NEVER does:
  - Generate content
  - Reason about problems
  - Send data anywhere
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from memory.models import ContextState, InferenceState, PerceptionData

logger = logging.getLogger(__name__)

# ── Regex patterns ───────────────────────────────────────────────────────────

# File extensions that indicate a document is open
_DOC_EXTENSIONS = re.compile(
    r'[\w\-. ]+\.(py|js|ts|jsx|tsx|go|rs|java|kt|swift|c|cpp|h|'
    r'md|txt|pdf|docx|xlsx|csv|json|yaml|yml|toml|html|css|sql|'
    r'sh|bash|zsh|rb|php|vue|svelte|dart|ex|exs|ml|r|ipynb)',
    re.IGNORECASE,
)

# Common separator patterns in IDE window titles
# "filename.py — ProjectName", "ProjectName › src › file.py", etc.
_PROJECT_SEPARATORS = re.compile(r'\s[—–·›>|•]\s|\s[-]{2}\s|:\s|\s/\s')

# Domain extraction from browser titles
# "Page Title — site.com", "GitHub - repo", "Stack Overflow - ..."
_DOMAIN_IN_TITLE = re.compile(
    r'(?:[-—–·|]\s*)([a-zA-Z0-9][a-zA-Z0-9\-]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)\s*$'
)
_KNOWN_SITES = {
    'github': 'github.com', 'stackoverflow': 'stackoverflow.com',
    'google': 'google.com', 'youtube': 'youtube.com',
    'reddit': 'reddit.com', 'twitter': 'twitter.com',
    'x.com': 'x.com', 'notion': 'notion.so',
    'figma': 'figma.com', 'linear': 'linear.app',
    'jira': 'jira.com', 'confluence': 'confluence.com',
    'slack': 'slack.com', 'discord': 'discord.com',
    'docs.google': 'docs.google.com', 'medium': 'medium.com',
    'dev.to': 'dev.to', 'hackernews': 'news.ycombinator.com',
    'mdn': 'developer.mozilla.org', 'pypi': 'pypi.org',
    'npm': 'npmjs.com', 'docker': 'hub.docker.com',
}

# Browser apps
_BROWSER_APPS = frozenset({
    'Safari', 'Google Chrome', 'Firefox', 'Arc', 'Microsoft Edge',
    'Brave Browser', 'Opera', 'Vivaldi', 'Chrome', 'Edge',
})

# Error keywords to watch for
_ERROR_PATTERNS = re.compile(
    r'(TypeError|ValueError|KeyError|AttributeError|ImportError|'
    r'ModuleNotFoundError|SyntaxError|IndentationError|NameError|'
    r'RuntimeError|Exception|FAILED|Error:|error:|Traceback|'
    r'undefined is not|Cannot read|NullPointerException|'
    r'AssertionError|PermissionError|FileNotFoundError|'
    r'ConnectionError|TimeoutError|panic:|fatal error)',
    re.MULTILINE,
)

# Max length for stored error hint
_ERROR_MAX_LEN = 120


# ── Dataclass for extracted entities ────────────────────────────────────────

class MemoryEntities:
    __slots__ = ('project', 'document', 'website', 'error_hint')

    def __init__(
        self,
        project:    Optional[str] = None,
        document:   Optional[str] = None,
        website:    Optional[str] = None,
        error_hint: Optional[str] = None,
    ) -> None:
        self.project    = project
        self.document   = document
        self.website    = website
        self.error_hint = error_hint


# ── Engine ────────────────────────────────────────────────────────────────────

class MemoryEngine:
    """
    Processes each perception tick and returns extracted entities.
    The caller (main.py) passes these to NeytreyadDB for persistence.
    """

    def extract(
        self,
        perception: PerceptionData,
        context:    ContextState,
        inference:  InferenceState,
    ) -> MemoryEntities:
        """Extract memorable entities from one perception tick."""
        title = (perception.window_title or '').strip()
        app   = (perception.active_app   or '').strip()
        text  = (perception.screen_text  or '').strip()

        is_browser = app in _BROWSER_APPS

        project  = None if is_browser else self._extract_project(title, app)
        document = None if is_browser else self._extract_document(title)
        website  = self._extract_website(title, app, is_browser)
        error    = self._extract_error(text, context.activity)

        return MemoryEntities(
            project=project,
            document=document,
            website=website,
            error_hint=error,
        )

    # ── Entity extractors ─────────────────────────────────────────────────

    def _extract_project(self, title: str, app: str) -> Optional[str]:
        """
        Heuristically extract a project name from a window title.

        VS Code: "main.py — my-project" → "my-project"
        Xcode:   "MyApp — Xcode"        → "MyApp"
        Terminal: titles often contain the cwd last segment
        """
        if not title:
            return None

        # Split on separators; take the longest non-filename segment
        parts = _PROJECT_SEPARATORS.split(title)
        candidates = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Skip if it looks like just a filename with extension
            if _DOC_EXTENSIONS.fullmatch(part):
                continue
            # Skip app names
            if part.lower() == app.lower():
                continue
            # Skip short or all-uppercase tokens (like "DEBUGGING", "ERROR")
            if len(part) < 2 or (part.isupper() and len(part) < 6):
                continue
            # Skip common non-project words
            if part.lower() in ('untitled', 'new file', 'terminal', 'bash', 'zsh'):
                continue
            candidates.append(part)

        if not candidates:
            return None

        # Prefer longer candidates (usually project names > file names)
        best = max(candidates, key=len)
        return best[:80] if len(best) > 2 else None

    def _extract_document(self, title: str) -> Optional[str]:
        """Extract document/file name from window title."""
        if not title:
            return None
        m = _DOC_EXTENSIONS.search(title)
        if m:
            # Walk back to find the full filename
            start = m.start()
            # Find the last path separator before the match
            seg = title[:m.end()]
            for sep in ('/', '\\', ' — ', ' – '):
                idx = seg.rfind(sep)
                if idx != -1:
                    seg = seg[idx + len(sep):]
            doc = seg.strip()
            return doc[:120] if doc else None
        return None

    def _extract_website(self, title: str, app: str, is_browser: bool) -> Optional[str]:
        """Extract domain from browser window title."""
        if not is_browser and app not in _BROWSER_APPS:
            return None
        if not title:
            return None

        # Check known site names in title
        title_lower = title.lower()
        for keyword, domain in _KNOWN_SITES.items():
            if keyword in title_lower:
                return domain

        # Try to extract domain from trailing "— domain.com" pattern
        m = _DOMAIN_IN_TITLE.search(title)
        if m:
            return m.group(1).lower()

        return None

    def _extract_error(self, screen_text: str, activity: str) -> Optional[str]:
        """Extract first error line from screen text if in a code context."""
        if not screen_text:
            return None
        if activity not in ('Coding', 'Debugging', 'Writing'):
            return None

        m = _ERROR_PATTERNS.search(screen_text)
        if not m:
            return None

        # Take the line containing the error
        start = screen_text.rfind('\n', 0, m.start()) + 1
        end   = screen_text.find('\n', m.end())
        if end == -1:
            end = m.end() + 60
        line = screen_text[start:end].strip()
        return line[:_ERROR_MAX_LEN] if line else None


    # ── Memory context: relate current to past ─────────────────────────────

    def build_memory_context(
        self,
        entities:        MemoryEntities,
        past_project:    Optional[dict],
        seen_error:      Optional[dict],
        related_website: Optional[dict],
    ) -> dict:
        """
        Build the `memory_context` dict that goes into the WS broadcast.
        Returns human-readable hints only — no reasoning, no solutions.
        """
        ctx: dict = {}

        if past_project:
            last_seen = past_project.get('last_seen', '')
            hours_ago = self._hours_ago(last_seen)
            total_h   = round((past_project.get('total_time_seconds', 0) or 0) / 3600, 1)
            if hours_ago is not None:
                if hours_ago < 1:
                    ctx['project_last_seen'] = 'You worked on this project less than an hour ago.'
                elif hours_ago < 24:
                    ctx['project_last_seen'] = f'You were working on this project {int(hours_ago)}h ago.'
                else:
                    days = int(hours_ago / 24)
                    ctx['project_last_seen'] = f'You last worked on this project {days}d ago.'
            if total_h > 0:
                ctx['project_total_time'] = f'{total_h}h total logged on this project.'

        if seen_error:
            count = seen_error.get('occurrence_count', 1)
            last  = seen_error.get('last_seen', '')
            hours = self._hours_ago(last)
            if count > 1 and hours is not None:
                when = f'{int(hours)}h ago' if hours < 24 else f'{int(hours/24)}d ago'
                ctx['seen_error'] = f"You've seen a similar error {count} times — last {when}."

        if related_website:
            ctx['related_site'] = f"You visited {related_website.get('domain', '')} while doing similar work before."

        return ctx

    @staticmethod
    def _hours_ago(iso_str: str) -> Optional[float]:
        if not iso_str:
            return None
        try:
            past = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            # Make now timezone-aware if past is
            now = datetime.now(past.tzinfo) if past.tzinfo else datetime.now()
            delta = now - past
            return delta.total_seconds() / 3600
        except Exception:
            return None
