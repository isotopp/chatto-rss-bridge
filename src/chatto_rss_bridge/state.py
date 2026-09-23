from __future__ import annotations

import sqlite3
from pathlib import Path


class StateError(RuntimeError):
    pass


class SeenStore:
    def __init__(self, path: Path) -> None:
        connection: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS seen "
                "(guid TEXT PRIMARY KEY, chatto_message_id TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS skipped (guid TEXT PRIMARY KEY)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pending_attempts ("
                "guid TEXT PRIMARY KEY, article_link TEXT NOT NULL, "
                "expected_body TEXT NOT NULL, status TEXT NOT NULL)"
            )
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise StateError("could not initialize state database") from exc
        assert connection is not None
        self._connection = connection

    def contains(self, guid: str) -> bool:
        try:
            row = self._connection.execute(
                "SELECT EXISTS(SELECT 1 FROM seen WHERE guid = ?) "
                "OR EXISTS(SELECT 1 FROM skipped WHERE guid = ?)",
                (guid, guid),
            ).fetchone()
            return row is not None and bool(row[0])
        except sqlite3.Error as exc:
            raise StateError("could not read state database") from exc

    def has_pending(self) -> bool:
        try:
            row = self._connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pending_attempts WHERE status = 'pending')"
            ).fetchone()
            return row is not None and bool(row[0])
        except sqlite3.Error as exc:
            raise StateError("could not read state database") from exc

    def begin_attempt(self, guid: str, article_link: str, body: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO pending_attempts "
                    "(guid, article_link, expected_body, status) "
                    "VALUES (?, ?, ?, 'pending')",
                    (guid, article_link, body),
                )
        except sqlite3.Error as exc:
            raise StateError("could not record posting attempt") from exc

    def discard_attempt(self, guid: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM pending_attempts WHERE guid = ?", (guid,)
                )
        except sqlite3.Error as exc:
            raise StateError("could not update state database") from exc

    def confirm(self, guid: str, message_id: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO seen (guid, chatto_message_id) VALUES (?, ?)",
                    (guid, message_id),
                )
                self._connection.execute(
                    "DELETE FROM pending_attempts WHERE guid = ?", (guid,)
                )
        except sqlite3.Error as exc:
            raise StateError("could not update state database") from exc

    def skip(self, guid: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT OR IGNORE INTO skipped (guid) VALUES (?)", (guid,)
                )
        except sqlite3.Error as exc:
            raise StateError("could not update state database") from exc

    def clear(self) -> None:
        try:
            pending_table = self._connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'pending_attempts'"
            ).fetchone()
            if pending_table is not None:
                pending = self._connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM pending_attempts WHERE status = 'pending')"
                ).fetchone()
                if pending is not None and bool(pending[0]):
                    raise StateError(
                        "cannot clear feed while a posting attempt is pending"
                    )
            with self._connection:
                self._connection.execute("DELETE FROM seen")
                self._connection.execute("DELETE FROM skipped")
        except sqlite3.Error as exc:
            raise StateError("could not clear state database") from exc

    def close(self) -> None:
        self._connection.close()
