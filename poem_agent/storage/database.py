"""SQLite persistence for drafts, approvals, publication history, and audit events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    poem TEXT NOT NULL,
                    author TEXT,
                    source TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','published','failed')),
                    scheduled_at TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    published_at TEXT,
                    telegram_message_id INTEGER,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_drafts_status_schedule ON drafts(status, scheduled_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    draft_id TEXT,
                    details TEXT NOT NULL DEFAULT '{}'
                );
            """)

    def create_draft(self, poem: str, *, author: str | None = None,
                     source: str | None = None, scheduled_at: str | None = None) -> str:
        poem = poem.strip()
        if len(poem) < 10:
            raise ValueError("Poem text is too short")
        draft_id = uuid.uuid4().hex[:10]
        with self.connect() as db:
            db.execute("""INSERT INTO drafts
                (id, poem, author, source, status, scheduled_at, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (draft_id, poem, author, source, scheduled_at, utc_now()))
        return draft_id

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
            return dict(row) if row else None

    def pending_drafts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM drafts WHERE status='pending' ORDER BY created_at LIMIT ?",
                              (limit,)).fetchall()
            return [dict(row) for row in rows]

    def approve(self, draft_id: str, owner_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("""UPDATE drafts SET status='approved', reviewed_by=?, reviewed_at=?
                WHERE id=? AND status='pending'""", (str(owner_id), utc_now(), draft_id))
            if cursor.rowcount:
                self._audit(db, owner_id, "approve", draft_id)
            return cursor.rowcount == 1

    def reject(self, draft_id: str, owner_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("""UPDATE drafts SET status='rejected', reviewed_by=?, reviewed_at=?
                WHERE id=? AND status='pending'""", (str(owner_id), utc_now(), draft_id))
            if cursor.rowcount:
                self._audit(db, owner_id, "reject", draft_id)
            return cursor.rowcount == 1

    def due_approved(self, limit: int = 20) -> list[dict[str, Any]]:
        now = utc_now()
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM drafts WHERE status='approved'
                AND (scheduled_at IS NULL OR scheduled_at <= ?) ORDER BY COALESCE(scheduled_at, created_at) LIMIT ?""",
                (now, limit)).fetchall()
            return [dict(row) for row in rows]

    def mark_published(self, draft_id: str, message_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("""UPDATE drafts SET status='published', published_at=?,
                telegram_message_id=?, error=NULL WHERE id=? AND status='approved'""",
                (utc_now(), message_id, draft_id))
            if cursor.rowcount:
                self._audit(db, "system", "published", draft_id, {"message_id": message_id})
            return cursor.rowcount == 1

    def mark_failed(self, draft_id: str, error: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("UPDATE drafts SET status='failed', error=? WHERE id=? AND status='approved'",
                                (error[:1000], draft_id))
            if cursor.rowcount:
                self._audit(db, "system", "publish_failed", draft_id, {"error": error[:300]})
            return cursor.rowcount == 1

    def _audit(self, db: sqlite3.Connection, actor_id: int | str, action: str,
               draft_id: str | None, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO audit_events(created_at, actor_id, action, draft_id, details) VALUES(?,?,?,?,?)",
                   (utc_now(), str(actor_id), action, draft_id,
                    json.dumps(details or {}, ensure_ascii=False)))
