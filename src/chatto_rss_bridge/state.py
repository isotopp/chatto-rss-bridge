from __future__ import annotations

import fcntl
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class StateError(RuntimeError):
    pass


class FeedExistsError(StateError):
    pass


class FeedNotFoundError(StateError):
    pass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    interval_minutes: int
    active: bool = True


@dataclass(frozen=True)
class FeedPendingAttempt:
    feed_name: str
    guid: str
    article_link: str
    expected_body: str


@dataclass(frozen=True)
class PendingAttempt:
    guid: str
    article_link: str
    expected_body: str


class SeenStore:
    def __init__(self, path: Path) -> None:
        connection: sqlite3.Connection | None = None
        self._path = path
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

    @contextmanager
    def locked(self) -> Iterator[None]:
        lock_path = self._path.with_name(self._path.name + ".lock")
        try:
            lock_file = lock_path.open("a+b")
        except OSError as exc:
            raise StateError("could not acquire state lock") from exc
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            lock_file.close()
            raise StateError("could not acquire state lock") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

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

    def pending_attempts(self) -> list[PendingAttempt]:
        try:
            rows = self._connection.execute(
                "SELECT guid, article_link, expected_body FROM pending_attempts "
                "WHERE status = 'pending' ORDER BY rowid"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StateError("could not read state database") from exc
        attempts = []
        for guid, article_link, expected_body in rows:
            if not all(
                isinstance(value, str) for value in (guid, article_link, expected_body)
            ):
                raise StateError("state database contains an invalid pending attempt")
            attempts.append(PendingAttempt(guid, article_link, expected_body))
        return attempts

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


class FeedStore:
    def __init__(self, path: Path) -> None:
        connection: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS feeds ("
                "name TEXT PRIMARY KEY, url TEXT NOT NULL, "
                "interval_minutes INTEGER NOT NULL CHECK(interval_minutes >= 10), "
                "active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)))"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(feeds)")}
            if "active" not in columns:
                connection.execute(
                    "ALTER TABLE feeds ADD COLUMN active INTEGER NOT NULL "
                    "DEFAULT 1 CHECK(active IN (0, 1))"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS feed_seen ("
                "feed_name TEXT NOT NULL, guid TEXT NOT NULL, "
                "chatto_message_id TEXT, PRIMARY KEY(feed_name, guid), "
                "FOREIGN KEY(feed_name) REFERENCES feeds(name) ON DELETE CASCADE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS feed_pending_attempts ("
                "feed_name TEXT NOT NULL, guid TEXT NOT NULL, "
                "article_link TEXT NOT NULL, expected_body TEXT NOT NULL, "
                "PRIMARY KEY(feed_name, guid), "
                "FOREIGN KEY(feed_name) REFERENCES feeds(name) ON DELETE RESTRICT)"
            )
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise StateError("could not initialize state database") from exc
        assert connection is not None
        self._connection = connection

    def add_feed(self, name: str, url: str, interval_minutes: int) -> Feed:
        feed = Feed(name, url, interval_minutes)
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO feeds (name, url, interval_minutes, active) "
                    "VALUES (?, ?, ?, 1)",
                    (feed.name, feed.url, feed.interval_minutes),
                )
        except sqlite3.IntegrityError as exc:
            if self._connection.execute(
                "SELECT 1 FROM feeds WHERE name = ?", (feed.name,)
            ).fetchone():
                raise FeedExistsError(f"feed already exists: {feed.name}") from exc
            raise StateError("invalid feed definition") from exc
        except sqlite3.Error as exc:
            raise StateError("could not add feed") from exc
        return feed

    def list_feeds(self) -> list[Feed]:
        try:
            rows = self._connection.execute(
                "SELECT name, url, interval_minutes, active FROM feeds "
                "WHERE active = 1 ORDER BY name"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StateError("could not list feeds") from exc
        return [Feed(row[0], row[1], row[2], bool(row[3])) for row in rows]

    def get_feed(self, name: str) -> Feed:
        try:
            row = self._connection.execute(
                "SELECT name, url, interval_minutes, active FROM feeds WHERE name = ?",
                (name,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StateError("could not find feed") from exc
        if row is None:
            raise FeedNotFoundError(f"feed not found: {name}")
        return Feed(row[0], row[1], row[2], bool(row[3]))

    def prepare_feed(
        self,
        name: str,
        url: str,
        interval_minutes: int,
        initial_guids: list[str],
        proof_guid: str,
        article_link: str,
        expected_body: str,
    ) -> Feed:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO feeds (name, url, interval_minutes, active) "
                    "VALUES (?, ?, ?, 0)",
                    (name, url, interval_minutes),
                )
                self._connection.executemany(
                    "INSERT OR IGNORE INTO feed_seen (feed_name, guid) VALUES (?, ?)",
                    ((name, guid) for guid in {*initial_guids, proof_guid}),
                )
                self._connection.execute(
                    "INSERT INTO feed_pending_attempts "
                    "(feed_name, guid, article_link, expected_body) "
                    "VALUES (?, ?, ?, ?)",
                    (name, proof_guid, article_link, expected_body),
                )
        except sqlite3.IntegrityError as exc:
            if self._connection.execute(
                "SELECT 1 FROM feeds WHERE name = ?", (name,)
            ).fetchone():
                raise FeedExistsError(f"feed already exists: {name}") from exc
            raise StateError("invalid feed definition") from exc
        except sqlite3.Error as exc:
            raise StateError("could not prepare feed") from exc
        return Feed(name, url, interval_minutes, False)

    def complete_feed_add(self, name: str, proof_guid: str, message_id: str) -> None:
        try:
            with self._connection:
                feed = self._connection.execute(
                    "SELECT active FROM feeds WHERE name = ?", (name,)
                ).fetchone()
                pending = self._connection.execute(
                    "SELECT 1 FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (name, proof_guid),
                ).fetchone()
                if feed is None or feed[0] or pending is None:
                    raise StateError("feed add has no matching pending proof post")
                self._connection.execute(
                    "INSERT INTO feed_seen (feed_name, guid, chatto_message_id) "
                    "VALUES (?, ?, ?) ON CONFLICT(feed_name, guid) DO UPDATE SET "
                    "chatto_message_id = coalesce(feed_seen.chatto_message_id, "
                    "excluded.chatto_message_id)",
                    (name, proof_guid, message_id),
                )
                self._connection.execute(
                    "DELETE FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (name, proof_guid),
                )
                self._connection.execute(
                    "UPDATE feeds SET active = 1 WHERE name = ?", (name,)
                )
        except StateError:
            raise
        except sqlite3.Error as exc:
            raise StateError("could not complete feed add") from exc

    def cancel_feed_add(self, name: str, proof_guid: str) -> None:
        try:
            with self._connection:
                feed = self._connection.execute(
                    "SELECT active FROM feeds WHERE name = ?", (name,)
                ).fetchone()
                pending = self._connection.execute(
                    "SELECT 1 FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (name, proof_guid),
                ).fetchone()
                if feed is None or feed[0] or pending is None:
                    raise StateError("feed add has no matching pending proof post")
                self._connection.execute(
                    "DELETE FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (name, proof_guid),
                )
                self._connection.execute("DELETE FROM feeds WHERE name = ?", (name,))
        except StateError:
            raise
        except sqlite3.Error as exc:
            raise StateError("could not cancel feed add") from exc

    def delete_feed(self, name: str) -> None:
        try:
            with self._connection:
                pending = self._connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM feed_pending_attempts "
                    "WHERE feed_name = ?)",
                    (name,),
                ).fetchone()
                if pending is not None and bool(pending[0]):
                    raise StateError("cannot delete feed with a pending post")
                cursor = self._connection.execute(
                    "DELETE FROM feeds WHERE name = ?", (name,)
                )
        except StateError:
            raise
        except sqlite3.Error as exc:
            raise StateError("could not delete feed") from exc
        if cursor.rowcount == 0:
            raise FeedNotFoundError(f"feed not found: {name}")

    def contains(self, feed_name: str, guid: str) -> bool:
        try:
            row = self._connection.execute(
                "SELECT EXISTS(SELECT 1 FROM feed_seen "
                "WHERE feed_name = ? AND guid = ?)",
                (feed_name, guid),
            ).fetchone()
            return row is not None and bool(row[0])
        except sqlite3.Error as exc:
            raise StateError("could not read feed history") from exc

    def mark_seen(
        self, feed_name: str, guid: str, message_id: str | None = None
    ) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO feed_seen (feed_name, guid, chatto_message_id) "
                    "VALUES (?, ?, ?) ON CONFLICT(feed_name, guid) DO UPDATE SET "
                    "chatto_message_id = coalesce(feed_seen.chatto_message_id, "
                    "excluded.chatto_message_id)",
                    (feed_name, guid, message_id),
                )
        except sqlite3.Error as exc:
            raise StateError("could not record feed history") from exc

    def pending_attempts(
        self, feed_name: str | None = None
    ) -> list[FeedPendingAttempt]:
        try:
            if feed_name is None:
                rows = self._connection.execute(
                    "SELECT feed_name, guid, article_link, expected_body "
                    "FROM feed_pending_attempts ORDER BY rowid"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT feed_name, guid, article_link, expected_body "
                    "FROM feed_pending_attempts WHERE feed_name = ? ORDER BY rowid",
                    (feed_name,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StateError("could not read pending feed posts") from exc
        return [FeedPendingAttempt(*row) for row in rows]

    def begin_attempt(
        self, feed_name: str, guid: str, article_link: str, expected_body: str
    ) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO feed_pending_attempts "
                    "(feed_name, guid, article_link, expected_body) "
                    "VALUES (?, ?, ?, ?)",
                    (feed_name, guid, article_link, expected_body),
                )
        except sqlite3.Error as exc:
            raise StateError("could not record pending feed post") from exc

    def discard_attempt(self, feed_name: str, guid: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (feed_name, guid),
                )
        except sqlite3.Error as exc:
            raise StateError("could not discard pending feed post") from exc

    def confirm(self, feed_name: str, guid: str, message_id: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO feed_seen (feed_name, guid, chatto_message_id) "
                    "VALUES (?, ?, ?) ON CONFLICT(feed_name, guid) DO UPDATE SET "
                    "chatto_message_id = coalesce(feed_seen.chatto_message_id, "
                    "excluded.chatto_message_id)",
                    (feed_name, guid, message_id),
                )
                self._connection.execute(
                    "DELETE FROM feed_pending_attempts "
                    "WHERE feed_name = ? AND guid = ?",
                    (feed_name, guid),
                )
        except sqlite3.Error as exc:
            raise StateError("could not confirm feed post") from exc

    def close(self) -> None:
        self._connection.close()
