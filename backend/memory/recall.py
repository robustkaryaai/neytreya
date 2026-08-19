"""
memory/recall.py
─────────────────
Recall Engine — searches the local activity timeline.

Answers questions like:
  - "When did I last work on this project?"
  - "Have I seen this error before?"
  - "What was I doing yesterday evening?"
  - "What website helped me last time?"

NEVER reasons, generates, or solves. Only retrieves structured memories.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from memory.db import NeytreyadDB


# ── Time helpers ─────────────────────────────────────────────────────────────

def _today()     -> str: return datetime.now().strftime('%Y-%m-%d')
def _yesterday() -> str: return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d')

def _fmt_ts(iso: str) -> str:
    """Human-readable timestamp from ISO string."""
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt
        hours = diff.total_seconds() / 3600
        if hours < 1:
            return f'{int(diff.total_seconds() / 60)}m ago'
        if hours < 24:
            return f'{int(hours)}h ago'
        days = int(hours / 24)
        if days == 1:
            return 'yesterday'
        return f'{days} days ago'
    except Exception:
        return iso[:16]


# ── Recall Engine ─────────────────────────────────────────────────────────────

class RecallEngine:
    """
    Searches the local activity database.
    Returns structured, factual results — never generated content.
    """

    def __init__(self, db: NeytreyadDB) -> None:
        self.db = db

    async def search(self, query: str) -> dict:
        """
        Full search across timeline, projects, websites and errors.
        Returns: { results: [...], summary: str }
        """
        q = query.strip()
        if not q or len(q) < 2:
            return {'results': [], 'summary': 'Type at least 2 characters to search.'}

        results = []

        # Search timeline
        timeline_rows = await self.db.search_timeline(q, limit=20)
        for row in timeline_rows:
            results.append({
                'type':      'timeline',
                'icon':      _activity_icon(row.get('activity', '')),
                'title':     row.get('app') or row.get('activity') or '—',
                'subtitle':  row.get('window_title') or row.get('workflow') or '',
                'time':      _fmt_ts(row['timestamp']) if row.get('timestamp') else '',
                'detail':    row.get('project') or row.get('website') or '',
            })

        # Search projects
        project_rows = await self.db.search_projects(q, limit=5)
        for row in project_rows:
            total_h = round((row.get('total_time_seconds') or 0) / 3600, 1)
            results.append({
                'type':     'project',
                'icon':     '📁',
                'title':    row.get('name') or '—',
                'subtitle': f"Last seen {_fmt_ts(row['last_seen'])}" if row.get('last_seen') else '',
                'time':     f'{total_h}h logged',
                'detail':   row.get('primary_app') or '',
            })

        # Search websites
        website_rows = await self.db.search_websites(q, limit=5)
        for row in website_rows:
            results.append({
                'type':     'website',
                'icon':     '🌐',
                'title':    row.get('domain') or '—',
                'subtitle': f"Visited {row.get('visit_count', 1)} times",
                'time':     _fmt_ts(row['last_seen']) if row.get('last_seen') else '',
                'detail':   row.get('typical_context') or '',
            })

        # Search errors
        error_rows = await self.db.search_errors(q, limit=5)
        for row in error_rows:
            results.append({
                'type':     'error',
                'icon':     '⚠',
                'title':    (row.get('error_pattern') or '—')[:80],
                'subtitle': f"Seen {row.get('occurrence_count', 1)} times in {row.get('app') or 'unknown app'}",
                'time':     _fmt_ts(row['last_seen']) if row.get('last_seen') else '',
                'detail':   '',
            })

        # Sort by recency where possible (timeline entries are already recent-first)
        total = len(results)
        summary = f'{total} result{"s" if total != 1 else ""} for "{q}"' if results else f'Nothing found for "{q}".'
        return {'results': results[:30], 'summary': summary}

    async def get_today(self) -> dict:
        """Return a structured summary of today's activity."""
        rows = await self.db.get_timeline_for_date(_today(), limit=200)
        return self._build_day_summary('Today', rows)

    async def get_yesterday(self) -> dict:
        """Return a structured summary of yesterday's activity."""
        rows = await self.db.get_timeline_for_date(_yesterday(), limit=200)
        return self._build_day_summary('Yesterday', rows)

    async def get_recent_timeline(self, limit: int = 40) -> list[dict]:
        """Return recent timeline entries for display."""
        rows = await self.db.get_recent_timeline(limit=limit)
        return [
            {
                'icon':     _activity_icon(r.get('activity', '')),
                'app':      r.get('app') or '—',
                'activity': r.get('activity') or '—',
                'workflow': r.get('workflow') or '',
                'project':  r.get('project') or '',
                'website':  r.get('website') or '',
                'document': r.get('document') or '',
                'error':    r.get('error_hint') or '',
                'time':     _fmt_ts(r['timestamp']) if r.get('timestamp') else '',
                'ts_raw':   r.get('timestamp', ''),
            }
            for r in rows
        ]

    async def get_project_history(self, project_name: str) -> dict:
        """Return history for a specific project."""
        rows = await self.db.search_timeline(project_name, limit=50)
        project = await self.db.get_project(project_name)
        return {
            'project': project,
            'entries': [
                {
                    'time':    _fmt_ts(r['timestamp']),
                    'app':     r.get('app'),
                    'workflow': r.get('workflow'),
                }
                for r in rows if r.get('project') and project_name.lower() in (r['project'] or '').lower()
            ],
        }

    # ── Internal ───────────────────────────────────────────────────────────

    def _build_day_summary(self, label: str, rows: list[dict]) -> dict:
        """Aggregate a day's timeline rows into an activity summary."""
        if not rows:
            return {'label': label, 'entries': [], 'summary': f'No activity recorded for {label.lower()}.'}

        # Group by activity
        activity_time: dict[str, int] = {}
        apps_seen: set[str] = set()
        projects_seen: set[str] = set()
        websites_seen: set[str] = set()
        errors_seen: set[str] = set()
        interval = 10  # seconds per tick (approximate)

        for row in rows:
            act = row.get('activity') or 'Unknown'
            activity_time[act] = activity_time.get(act, 0) + interval
            if row.get('app'):     apps_seen.add(row['app'])
            if row.get('project'): projects_seen.add(row['project'])
            if row.get('website'): websites_seen.add(row['website'])
            if row.get('error_hint'): errors_seen.add(row['error_hint'][:60])

        # Build entries sorted by time spent
        entries = [
            {
                'icon':     _activity_icon(act),
                'activity': act,
                'minutes':  round(secs / 60, 1),
                'label':    f'{round(secs / 60)}m',
            }
            for act, secs in sorted(activity_time.items(), key=lambda x: -x[1])
        ]

        return {
            'label':     label,
            'entries':   entries,
            'apps':      sorted(apps_seen),
            'projects':  sorted(projects_seen),
            'websites':  sorted(websites_seen),
            'errors':    list(errors_seen)[:5],
            'total_minutes': round(sum(activity_time.values()) / 60, 1),
            'summary':   f'{label}: {round(sum(activity_time.values()) / 3600, 1)}h of activity recorded.',
        }


def _activity_icon(activity: str) -> str:
    return {
        'Coding':     '⟨/⟩',
        'Debugging':  '🔍',
        'Browsing':   '🌐',
        'Researching':'🔬',
        'Writing':    '✍',
        'Designing':  '🎨',
        'Meeting':    '👥',
        'Studying':   '📚',
        'Idle':       '◌',
    }.get(activity, '◈')
