"""
MAVERICK storage module (Phase 1).

SQLite persistence for all chat messages. Each CLI run can use a session
(`session_id`) so history stays grouped; personality is stored per message
for filtering and display.

Default database file: `maverick.db` in the current working directory.
(Keep `*.db` in `.gitignore`.)
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from logger import MaverickLogger, create_logger


DEFAULT_DB_NAME = "maverick.db"


def _utc_iso(ts: float) -> str:
    # Simple ISO-like string for display/export (local naive is fine for Phase 1).
    from datetime import datetime

    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


class ConversationStorage:
    """
    Save and load conversation rows in SQLite.

    Schema:
    - sessions: one row per chat session
    - messages: one row per user/assistant turn
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_NAME,
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
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        personality TEXT NOT NULL DEFAULT '',
                        started_at REAL NOT NULL,
                        title TEXT
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        personality TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_session_time
                        ON messages(session_id, created_at);
                    """
                )
            self.logger.memory(f"Storage ready at {self.db_path}")
        except OSError as exc:
            self.logger.error(f"Storage init failed: {exc}")
            raise

    def new_session(self, personality: str = "", title: Optional[str] = None) -> str:
        """Create a new session row; returns session_id (UUID)."""
        sid = str(uuid.uuid4())
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO sessions (id, personality, started_at, title) VALUES (?, ?, ?, ?)",
                    (sid, personality.strip(), now, title),
                )
            self.logger.memory(f"New session {sid[:8]}… personality={personality!r}")
        except sqlite3.Error as exc:
            self.logger.error(f"new_session failed: {exc}")
            raise
        return sid

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        personality: str = "",
    ) -> int:
        """
        Insert one message. `role` is typically 'user', 'assistant', or 'system'.
        Returns the new message row id.
        """
        now = time.time()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, personality, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, personality.strip(), now),
                )
                mid = int(cur.lastrowid or 0)
            self.logger.memory(
                f"Saved message id={mid} role={role!r} session={session_id[:8]}…"
            )
            return mid
        except sqlite3.Error as exc:
            self.logger.error(f"append_message failed: {exc}")
            raise

    def get_recent_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[dict[str, Any]]:
        """Return recent messages for API context (oldest first within the slice)."""
        if limit < 1:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, session_id, role, content, personality, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            self.logger.error(f"get_recent_messages failed: {exc}")
            raise

        out: List[dict[str, Any]] = []
        for r in reversed(rows):
            out.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "personality": r["personality"],
                    "created_at": r["created_at"],
                    "created_at_iso": _utc_iso(float(r["created_at"])),
                }
            )
        return out

    def get_history_for_api(
        self,
        session_id: str,
        limit: int = 30,
    ) -> List[dict[str, str]]:
        """
        Format last N turns as OpenAI-style messages for the router
        (only user/assistant roles with string content).
        """
        rows = self.get_recent_messages(session_id, limit=limit)
        api: List[dict[str, str]] = []
        for row in rows:
            role = row["role"]
            if role not in ("user", "assistant", "system"):
                continue
            api.append({"role": role, "content": row["content"]})
        return api

    def list_sessions(self, limit: int = 20) -> List[dict[str, Any]]:
        """Most recent sessions first."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT s.id, s.personality, s.started_at, s.title,
                           (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS msg_count
                    FROM sessions s
                    ORDER BY s.started_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            self.logger.error(f"list_sessions failed: {exc}")
            raise

        return [
            {
                "id": r["id"],
                "personality": r["personality"],
                "started_at": r["started_at"],
                "started_at_iso": _utc_iso(float(r["started_at"])),
                "title": r["title"],
                "message_count": r["msg_count"],
            }
            for r in rows
        ]

    def session_exists(self, session_id: str) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            self.logger.error(f"session_exists failed: {exc}")
            raise


def create_storage(
    db_path: str | Path = DEFAULT_DB_NAME,
    logger: Optional[MaverickLogger] = None,
) -> ConversationStorage:
    return ConversationStorage(db_path=db_path, logger=logger)
