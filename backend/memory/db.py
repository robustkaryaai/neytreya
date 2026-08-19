from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from memory.models import PerceptionData

DATA_DIR = Path.home() / ".neytreya"
DB_PATH = DATA_DIR / "neytreya.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    active_app      TEXT,
    window_title    TEXT,
    screen_text     TEXT,
    vision_summary  TEXT,
    clipboard_text  TEXT,
    cpu_percent     REAL,
    ram_percent     REAL,
    ram_available_gb REAL,
    battery_percent REAL,
    battery_plugged INTEGER,
    load_tier       TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    dominant_context    TEXT,
    inferred_workflow   TEXT,
    apps_used           TEXT,   -- JSON array
    observations_json   TEXT    -- JSON array
);

CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    episode_id  INTEGER,
    message     TEXT NOT NULL,
    obs_type    TEXT,
    shown       INTEGER DEFAULT 0,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);

CREATE TABLE IF NOT EXISTS stuck_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT,
    ended_at        TEXT,
    signals_json    TEXT,
    rk_ai_invoked   INTEGER DEFAULT 0,
    context_json    TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- ── Memory & Recall tables ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS timeline (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    date            TEXT    NOT NULL,       -- YYYY-MM-DD
    hour            INTEGER,               -- 0-23
    app             TEXT,
    window_title    TEXT,
    activity        TEXT,                  -- Coding / Browsing / …
    workflow        TEXT,                  -- Deep Focus / Debugging / …
    project         TEXT,                  -- extracted project name
    document        TEXT,                  -- extracted filename
    website         TEXT,                  -- extracted domain
    error_hint      TEXT,                  -- first line of error if any
    duration_seconds INTEGER DEFAULT 0     -- filled in by UPDATE on next tick
);

CREATE INDEX IF NOT EXISTS idx_timeline_date     ON timeline(date);
CREATE INDEX IF NOT EXISTS idx_timeline_app      ON timeline(app);
CREATE INDEX IF NOT EXISTS idx_timeline_project  ON timeline(project);
CREATE INDEX IF NOT EXISTS idx_timeline_website  ON timeline(website);

CREATE TABLE IF NOT EXISTS projects (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    UNIQUE NOT NULL,
    first_seen          TEXT,
    last_seen           TEXT,
    total_time_seconds  INTEGER DEFAULT 0,
    primary_app         TEXT,
    session_count       INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);

CREATE TABLE IF NOT EXISTS websites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT    UNIQUE NOT NULL,
    first_seen      TEXT,
    last_seen       TEXT,
    visit_count     INTEGER DEFAULT 0,
    typical_context TEXT
);

CREATE INDEX IF NOT EXISTS idx_websites_domain ON websites(domain);

CREATE TABLE IF NOT EXISTS seen_errors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    error_pattern    TEXT    NOT NULL,
    first_seen       TEXT,
    last_seen        TEXT,
    occurrence_count INTEGER DEFAULT 1,
    app              TEXT,
    context          TEXT
);

CREATE INDEX IF NOT EXISTS idx_errors_pattern ON seen_errors(error_pattern);

CREATE TABLE IF NOT EXISTS recall_summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    date         TEXT NOT NULL,
    snapshot_path TEXT,
    app          TEXT,
    window_title TEXT,
    summary      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recall_date ON recall_summaries(date);
"""


# ---------------------------------------------------------------------------
# DB Manager
# ---------------------------------------------------------------------------

class NeytreyadDB:
    """Async SQLite database manager for Neytreya."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._last_timeline_id: Optional[int] = None

    async def init(self) -> None:
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    # ── Snapshots ───────────────────────────────────────────────────────────

    async def save_snapshot(self, perception: PerceptionData) -> int:
        """Persist a perception snapshot and return its row ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO snapshots (
                    timestamp, active_app, window_title, screen_text,
                    vision_summary, clipboard_text,
                    cpu_percent, ram_percent, ram_available_gb,
                    battery_percent, battery_plugged, load_tier
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    perception.timestamp,
                    perception.active_app,
                    perception.window_title,
                    perception.screen_text,
                    perception.vision_summary,
                    perception.clipboard_text,
                    perception.cpu_percent,
                    perception.ram_percent,
                    perception.ram_available_gb,
                    perception.battery_percent,
                    int(perception.battery_plugged) if perception.battery_plugged is not None else None,
                    perception.load_tier,
                ),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_recent_snapshots(self, limit: int = 50) -> list[dict]:
        """Return the most recent perception snapshots."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Timeline ────────────────────────────────────────────────────────────

    async def record_timeline(
        self,
        perception: PerceptionData,
        activity:   str,
        workflow:   str,
        project:    Optional[str] = None,
        document:   Optional[str] = None,
        website:    Optional[str] = None,
        error_hint: Optional[str] = None,
        interval_seconds: int = 10,
    ) -> int:
        """Insert a timeline entry and close the previous entry's duration."""
        now_str = perception.timestamp or datetime.now().isoformat()
        try:
            dt   = datetime.fromisoformat(now_str.replace('Z', '+00:00'))
            date = dt.strftime('%Y-%m-%d')
            hour = dt.hour
        except Exception:
            date = datetime.now().strftime('%Y-%m-%d')
            hour = datetime.now().hour

        async with aiosqlite.connect(self.db_path) as db:
            # Close previous entry
            if self._last_timeline_id is not None:
                await db.execute(
                    "UPDATE timeline SET duration_seconds = ? WHERE id = ?",
                    (interval_seconds, self._last_timeline_id),
                )

            cursor = await db.execute(
                """
                INSERT INTO timeline
                    (timestamp, date, hour, app, window_title,
                     activity, workflow, project, document, website, error_hint)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (now_str, date, hour,
                 perception.active_app, perception.window_title,
                 activity, workflow,
                 project, document, website, error_hint),
            )
            await db.commit()
            self._last_timeline_id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_recent_timeline(self, limit: int = 40) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM timeline ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_timeline_for_date(self, date: str, limit: int = 500) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM timeline WHERE date = ? ORDER BY id ASC LIMIT ?",
                (date, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def search_timeline(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across timeline text columns."""
        like = f'%{query}%'
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM timeline
                WHERE app LIKE ? OR window_title LIKE ? OR activity LIKE ?
                   OR project LIKE ? OR document LIKE ? OR website LIKE ?
                   OR workflow LIKE ? OR error_hint LIKE ?
                ORDER BY id DESC LIMIT ?
                """,
                (like, like, like, like, like, like, like, like, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Projects ─────────────────────────────────────────────────────────────

    async def upsert_project(
        self,
        name:       str,
        app:        Optional[str],
        interval_s: int = 10,
    ) -> None:
        """Insert or update a project record."""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            row = await (await db.execute(
                "SELECT id, primary_app, total_time_seconds FROM projects WHERE name = ?", (name,)
            )).fetchone()

            if row:
                await db.execute(
                    """UPDATE projects
                       SET last_seen = ?, total_time_seconds = total_time_seconds + ?,
                           session_count = session_count + 1,
                           primary_app = COALESCE(?, primary_app)
                       WHERE name = ?""",
                    (now, interval_s, app, name),
                )
            else:
                await db.execute(
                    """INSERT INTO projects (name, first_seen, last_seen, total_time_seconds, primary_app, session_count)
                       VALUES (?,?,?,?,?,1)""",
                    (name, now, now, interval_s, app),
                )
            await db.commit()

    async def get_project(self, name: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM projects WHERE name LIKE ?", (f'%{name}%',)
            )).fetchone()
            return dict(row) if row else None

    async def search_projects(self, query: str, limit: int = 5) -> list[dict]:
        like = f'%{query}%'
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM projects WHERE name LIKE ? ORDER BY last_seen DESC LIMIT ?",
                (like, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]

    # ── Websites ──────────────────────────────────────────────────────────────

    async def upsert_website(self, domain: str, context: Optional[str]) -> None:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            row = await (await db.execute(
                "SELECT id FROM websites WHERE domain = ?", (domain,)
            )).fetchone()

            if row:
                await db.execute(
                    """UPDATE websites
                       SET last_seen = ?, visit_count = visit_count + 1,
                           typical_context = COALESCE(?, typical_context)
                       WHERE domain = ?""",
                    (now, context, domain),
                )
            else:
                await db.execute(
                    """INSERT INTO websites (domain, first_seen, last_seen, visit_count, typical_context)
                       VALUES (?,?,?,1,?)""",
                    (domain, now, now, context),
                )
            await db.commit()

    async def search_websites(self, query: str, limit: int = 5) -> list[dict]:
        like = f'%{query}%'
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM websites WHERE domain LIKE ? OR typical_context LIKE ? ORDER BY last_seen DESC LIMIT ?",
                (like, like, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]

    # ── Errors ────────────────────────────────────────────────────────────────

    async def upsert_error(self, pattern: str, app: Optional[str], context: Optional[str]) -> None:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            # Fuzzy match: look for exact or very similar pattern
            row = await (await db.execute(
                "SELECT id FROM seen_errors WHERE error_pattern = ?", (pattern,)
            )).fetchone()

            if row:
                await db.execute(
                    """UPDATE seen_errors
                       SET last_seen = ?, occurrence_count = occurrence_count + 1,
                           app = COALESCE(?, app)
                       WHERE id = ?""",
                    (now, app, row[0]),
                )
            else:
                await db.execute(
                    """INSERT INTO seen_errors (error_pattern, first_seen, last_seen, occurrence_count, app, context)
                       VALUES (?,?,?,1,?,?)""",
                    (pattern, now, now, app, context),
                )
            await db.commit()

    async def find_similar_error(self, pattern: str) -> Optional[dict]:
        """Find a previously seen error matching this pattern (fuzzy)."""
        sig = pattern[:40]
        like = f'%{sig}%'
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM seen_errors WHERE error_pattern LIKE ? ORDER BY occurrence_count DESC LIMIT 1",
                (like,),
            )).fetchone()
            return dict(row) if row else None

    async def search_errors(self, query: str, limit: int = 5) -> list[dict]:
        like = f'%{query}%'
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM seen_errors WHERE error_pattern LIKE ? ORDER BY last_seen DESC LIMIT ?",
                (like, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]

    # ── Active Recall Summaries ──────────────────────────────────────────────

    async def save_recall_summary(
        self,
        summary:       str,
        app:           Optional[str] = None,
        window_title:  Optional[str] = None,
        snapshot_path: Optional[str] = None,
    ) -> int:
        """Persist a Qwen-generated recall summary."""
        now = datetime.now().isoformat()
        date = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO recall_summaries (timestamp, date, snapshot_path, app, window_title, summary)
                VALUES (?,?,?,?,?,?)
                """,
                (now, date, snapshot_path, app, window_title, summary),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_recall_summaries_for_date(self, date: str, limit: int = 200) -> list[dict]:
        """Return all recall summaries for a given date (YYYY-MM-DD)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM recall_summaries WHERE date = ? ORDER BY timestamp ASC LIMIT ?",
                (date, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def get_recent_recall_summaries(self, limit: int = 20) -> list[dict]:
        """Return the most recent recall summaries."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM recall_summaries ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]

