"""
MAVERICK pattern learning engine (Phase 2).

Tracks:
- Active usage by hour
- Most used commands
- Command category patterns (study/github/work/general)

Provides suggestions and summary data for `my patterns`.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from logger import MaverickLogger, create_logger


DEFAULT_PATTERN_DB = "patterns.db"


class PatternEngine:
    """SQLite-based usage pattern tracker."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_PATTERN_DB,
        logger: Optional[MaverickLogger] = None,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.logger = logger or create_logger()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    category TEXT NOT NULL,
                    hour INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_activity_hour
                    ON activity_events(hour);
                CREATE INDEX IF NOT EXISTS idx_activity_command
                    ON activity_events(command);
                CREATE INDEX IF NOT EXISTS idx_activity_category
                    ON activity_events(category);
                """
            )
        self.logger.memory(f"Pattern engine ready at {self.db_path}")

    def record_command(self, command_text: str, when_ts: Optional[float] = None) -> None:
        raw = (command_text or "").strip()
        if not raw:
            return
        ts = float(when_ts if when_ts is not None else time.time())
        hour = int(time.localtime(ts).tm_hour)
        category = self._infer_category(raw)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_events (command, category, hour, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (raw.lower(), category, hour, ts),
            )

    def top_hours(self, limit: int = 5) -> list[tuple[int, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT hour, COUNT(*) AS c
                FROM activity_events
                GROUP BY hour
                ORDER BY c DESC, hour ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [(int(r["hour"]), int(r["c"])) for r in rows]

    def top_commands(self, limit: int = 8) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT command, COUNT(*) AS c
                FROM activity_events
                GROUP BY command
                ORDER BY c DESC, command ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [(str(r["command"]), int(r["c"])) for r in rows]

    def top_categories(self, limit: int = 4) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS c
                FROM activity_events
                GROUP BY category
                ORDER BY c DESC, category ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [(str(r["category"]), int(r["c"])) for r in rows]

    def predict_now(self, when_ts: Optional[float] = None) -> str:
        """
        Predict likely focus based on current hour and historical category patterns.
        """
        ts = float(when_ts if when_ts is not None else time.time())
        hour = int(time.localtime(ts).tm_hour)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT category, COUNT(*) AS c
                FROM activity_events
                WHERE hour = ?
                GROUP BY category
                ORDER BY c DESC
                LIMIT 1
                """,
                (hour,),
            ).fetchone()
        if not row:
            return "No pattern yet. Keep using MAVERICK and I will learn your routine."
        category = str(row["category"])
        return self._suggestion_for_category(category, hour)

    def patterns_report(self) -> str:
        hours = self.top_hours()
        commands = self.top_commands()
        cats = self.top_categories()
        prediction = self.predict_now()

        if not hours and not commands:
            return "No pattern data yet. Use MAVERICK commands and ask again."

        htxt = ", ".join(f"{h:02d}:00 ({c})" for h, c in hours) or "none"
        ctxt = ", ".join(f"{cmd} ({c})" for cmd, c in commands) or "none"
        catxt = ", ".join(f"{cat} ({c})" for cat, c in cats) or "none"

        return (
            f"Top active hours: {htxt}\n"
            f"Most used commands: {ctxt}\n"
            f"Pattern categories: {catxt}\n"
            f"Suggestion now: {prediction}"
        )

    @staticmethod
    def _infer_category(command_text: str) -> str:
        text = command_text.lower()
        if any(x in text for x in ("study", "subject", "learn", "java", "python", "college", "exam")):
            return "study"
        if any(x in text for x in ("github", "git", "commit", "push", "pull", "repo", "branch")):
            return "github"
        if any(x in text for x in ("work", "project", "client", "meeting", "task", "office")):
            return "work"
        return "general"

    @staticmethod
    def _suggestion_for_category(category: str, hour: int) -> str:
        if category == "study":
            return f"{hour:02d}:00 is usually a study hour. Open your subject notes and do a 25-minute session."
        if category == "github":
            return f"{hour:02d}:00 often matches coding flow. Review your repo tasks and push one clean update."
        if category == "work":
            return f"{hour:02d}:00 looks like work mode. Prioritize your top task and close one pending item."
        return f"{hour:02d}:00 is generally active time. Pick one meaningful task and complete it now."


def create_pattern_engine(
    db_path: str | Path = DEFAULT_PATTERN_DB,
    logger: Optional[MaverickLogger] = None,
) -> PatternEngine:
    return PatternEngine(db_path=db_path, logger=logger)
