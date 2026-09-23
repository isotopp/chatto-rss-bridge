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
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise StateError("could not initialize state database") from exc
        assert connection is not None
        self._connection = connection

    def contains(self, guid: str) -> bool:
        try:
            return (
                self._connection.execute(
                    "SELECT 1 FROM seen WHERE guid = ?", (guid,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error as exc:
            raise StateError("could not read state database") from exc

    def confirm(self, guid: str, message_id: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO seen (guid, chatto_message_id) VALUES (?, ?)",
                    (guid, message_id),
                )
        except sqlite3.Error as exc:
            raise StateError("could not update state database") from exc

    def close(self) -> None:
        self._connection.close()
