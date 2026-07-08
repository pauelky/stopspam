from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Database:
    def __init__(self, path: Path, clean_limit: int) -> None:
        self.path = path
        self.clean_limit = clean_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS clean_mutes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    duration_minutes INTEGER,
                    reason TEXT,
                    muted_until TEXT,
                    status TEXT,
                    deleted_count INTEGER DEFAULT 0,
                    cleaned_old_count INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_clean_mutes_active
                ON clean_mutes(chat_id, user_id, status, muted_until)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS delete_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    message_id INTEGER,
                    reason TEXT,
                    created_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS read_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    message_id INTEGER,
                    created_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS read_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    type TEXT,
                    created_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_read_blacklist_unique
                ON read_blacklist(chat_id, user_id, type)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    data TEXT,
                    created_at TEXT
                )
                """
            )
            defaults = {
                "notify_mute_expired": "false",
                "clean_limit": str(self.clean_limit),
                "delete_command_messages": "true",
                "auto_read_enabled": "false",
            }
            for key, value in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, value),
                )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def bool_setting(self, key: str, default: bool = False) -> bool:
        value = self.get_setting(key, "true" if default else "false")
        return str(value).lower() in {"1", "true", "yes", "on"}

    def add_log(self, action: str, data: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO logs(action, data, created_at) VALUES(?, ?, ?)",
                (action, json.dumps(data, ensure_ascii=False), iso()),
            )

    def upsert_mute(
        self,
        chat_id: int,
        user_id: int,
        username: str,
        duration_minutes: int,
        reason: str,
        muted_until: datetime,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE clean_mutes
                SET status = 'replaced'
                WHERE chat_id = ? AND user_id = ? AND status = 'active'
                """,
                (chat_id, user_id),
            )
            db.execute(
                """
                INSERT INTO clean_mutes(
                    chat_id, user_id, username, duration_minutes, reason,
                    muted_until, status, deleted_count, cleaned_old_count, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, 'active', 0, 0, ?)
                """,
                (chat_id, user_id, username, duration_minutes, reason, iso(muted_until), iso()),
            )

    def active_mute(self, chat_id: int, user_id: int) -> sqlite3.Row | None:
        now = iso()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT *
                FROM clean_mutes
                WHERE chat_id = ? AND user_id = ? AND status = 'active' AND muted_until > ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, user_id, now),
            ).fetchone()
        return row

    def deactivate_mute(self, chat_id: int, user_id: int, status: str = "unmuted") -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE clean_mutes
                SET status = ?
                WHERE chat_id = ? AND user_id = ? AND status = 'active'
                """,
                (status, chat_id, user_id),
            )
            return cursor.rowcount

    def list_active_mutes(self, chat_id: int) -> list[sqlite3.Row]:
        now = iso()
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM clean_mutes
                WHERE chat_id = ? AND status = 'active' AND muted_until > ?
                ORDER BY muted_until ASC
                """,
                (chat_id, now),
            ).fetchall()
        return list(rows)

    def increment_deleted(self, mute_id: int, chat_id: int, user_id: int, message_id: int, reason: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE clean_mutes SET deleted_count = deleted_count + 1 WHERE id = ?",
                (mute_id,),
            )
            db.execute(
                """
                INSERT INTO delete_logs(chat_id, user_id, message_id, reason, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, message_id, reason, iso()),
            )

    def add_cleaned_old(self, chat_id: int, user_id: int, count: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE clean_mutes
                SET cleaned_old_count = cleaned_old_count + ?
                WHERE chat_id = ? AND user_id = ? AND status = 'active'
                """,
                (count, chat_id, user_id),
            )

    def expire_old_mutes(self) -> list[sqlite3.Row]:
        now = iso()
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM clean_mutes WHERE status = 'active' AND muted_until <= ?",
                (now,),
            ).fetchall()
            db.execute(
                "UPDATE clean_mutes SET status = 'expired' WHERE status = 'active' AND muted_until <= ?",
                (now,),
            )
        return list(rows)

    def add_read_log(self, chat_id: int, user_id: int, message_id: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO read_logs(chat_id, user_id, message_id, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (chat_id, user_id, message_id, iso()),
            )

    def read_count_today(self) -> int:
        start = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC).isoformat()
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM read_logs WHERE created_at >= ?",
                (start,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def add_read_blacklist(self, chat_id: int | None, user_id: int | None, item_type: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO read_blacklist(chat_id, user_id, type, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (chat_id, user_id, item_type, iso()),
            )

    def remove_read_blacklist(self, chat_id: int | None, user_id: int | None, item_type: str) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                DELETE FROM read_blacklist
                WHERE chat_id IS ? AND user_id IS ? AND type = ?
                """,
                (chat_id, user_id, item_type),
            )
            return cursor.rowcount

    def is_read_blacklisted(self, chat_id: int, user_id: int | None) -> bool:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT 1
                FROM read_blacklist
                WHERE (type = 'chat' AND chat_id = ?)
                   OR (type = 'user' AND user_id = ?)
                LIMIT 1
                """,
                (chat_id, user_id),
            ).fetchone()
        return row is not None

    def list_read_blacklist(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM read_blacklist ORDER BY created_at DESC"
            ).fetchall()
        return list(rows)
