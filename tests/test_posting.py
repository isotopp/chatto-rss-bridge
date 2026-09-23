import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, tzinfo
from pathlib import Path
from threading import Event, Lock
from typing import Self

import httpx

from chatto_rss_bridge import main, runner

RSS_ITEM = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Presseschau</title><item>
<title>Presseschau today</title>
<link>https://www.deutschlandfunk.de/example-episode</link>
<description>A concise summary of today's episode.</description>
<guid>episode-guid-1</guid>
<pubDate>Wed, 23 Sep 2026 07:05:03 +0200</pubDate>
</item></channel></rss>
"""


def _seed_pending_attempt(database_path: Path, expected_body: str) -> None:
    with sqlite3.connect(database_path) as database:
        database.execute(
            "CREATE TABLE seen (guid TEXT PRIMARY KEY, chatto_message_id TEXT NOT NULL)"
        )
        database.execute("CREATE TABLE skipped (guid TEXT PRIMARY KEY)")
        database.execute(
            "CREATE TABLE pending_attempts ("
            "guid TEXT PRIMARY KEY, article_link TEXT NOT NULL, "
            "expected_body TEXT NOT NULL, status TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO pending_attempts VALUES (?, ?, ?, 'pending')",
            (
                "episode-guid-1",
                "https://www.deutschlandfunk.de/example-episode",
                expected_body,
            ),
        )


def test_one_feed_item_is_posted_as_an_authenticated_root_message(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            assert str(request.url) == "https://feed.example/presseschau.xml"
            return httpx.Response(
                200, content=RSS_ITEM, headers={"Content-Type": "application/rss+xml"}
            )

        assert request.method == "POST"
        assert (
            request.url.path
            == "/api/connect/chatto.api.v1.MessageService/CreateMessage"
        )
        assert request.headers["Authorization"] == "Bearer test-api-key"
        body = json.loads(request.content)
        assert body["roomId"] == "room-1"
        assert "threadRootEventId" not in body
        assert body.get("createThread") is not True
        message = body["body"]
        assert "Presseschau today" in message
        assert "A concise summary of today's episode." in message
        assert "https://www.deutschlandfunk.de/example-episode" in message
        return httpx.Response(200, json={"message": {"id": "chatto-message-1"}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    assert result == 0
    assert [request.method for request in requests] == ["GET", "POST"]
    assert "Presseschau today" in capsys.readouterr().out


def test_confirmed_guid_is_persisted_and_only_new_items_are_posted(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    two_items = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>New episode</title><link>https://example.com/new</link>
        <description>New summary.</description><guid>new-guid</guid>
        <pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate></item>
      <item><title>Old episode</title><link>https://example.com/old</link>
        <description>Old summary.</description><guid>old-guid</guid>
        <pubDate>Wed, 23 Sep 2026 07:05:03 +0200</pubDate></item>
    </channel></rss>"""
    three_items = two_items.replace(
        b"<channel>",
        b"""<channel><item><title>Third episode</title>
        <link>https://example.com/third</link>
        <description>Third summary.</description><guid>third-guid</guid>
        <pubDate>Fri, 25 Sep 2026 07:05:03 +0200</pubDate></item>""",
        1,
    )
    feed = two_items
    posted_bodies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=feed)
        posted_bodies.append(json.loads(request.content)["body"])
        return httpx.Response(
            200, json={"message": {"id": f"chatto-message-{len(posted_bodies)}"}}
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    def run() -> int:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            return main([], http_client=client)

    assert run() == 0
    assert run() == 0
    feed = three_items
    assert run() == 0

    assert [body.splitlines()[0] for body in posted_bodies] == [
        "Old episode",
        "New episode",
        "Third episode",
    ]
    with sqlite3.connect(tmp_path / ".chatto-rss-bridge.db") as database:
        saved = database.execute(
            "SELECT guid, chatto_message_id FROM seen ORDER BY rowid"
        ).fetchall()
    assert saved == [
        ("old-guid", "chatto-message-1"),
        ("new-guid", "chatto-message-2"),
        ("third-guid", "chatto-message-3"),
    ]


def test_first_run_posts_only_today_and_marks_older_items_seen(
    monkeypatch, tmp_path: Path
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(2026, 10, 25, 12, 0, tzinfo=tz)

    monkeypatch.setattr(runner, "datetime", FixedDateTime)
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    # The two current-day episodes fall on either side of Berlin's DST change.
    feed = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>Today late</title><link>https://example.com/late</link>
        <description>Late summary.</description><guid>today-late</guid>
        <pubDate>Sun, 25 Oct 2026 01:30:00 +0000</pubDate></item>
      <item><title>Today early</title><link>https://example.com/early</link>
        <description>Early summary.</description><guid>today-early</guid>
        <pubDate>Sat, 24 Oct 2026 22:30:00 +0000</pubDate></item>
      <item><title>Yesterday</title><link>https://example.com/yesterday</link>
        <description>Yesterday summary.</description><guid>yesterday</guid>
        <pubDate>Sat, 24 Oct 2026 21:30:00 +0000</pubDate></item>
    </channel></rss>"""
    posted_titles: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=feed)
        body = json.loads(request.content)["body"]
        posted_titles.append(body.splitlines()[0])
        return httpx.Response(
            200, json={"message": {"id": f"chatto-message-{len(posted_titles)}"}}
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main(["--first-run"], http_client=client) == 0
        assert main([], http_client=client) == 0

    assert posted_titles == ["Today early", "Today late"]
    with sqlite3.connect(tmp_path / ".chatto-rss-bridge.db") as database:
        confirmed = database.execute("SELECT guid FROM seen ORDER BY rowid").fetchall()
        skipped = database.execute("SELECT guid FROM skipped").fetchall()
    assert confirmed == [("today-early",), ("today-late",)]
    assert skipped == [("yesterday",)]


def test_clear_feed_resets_state_without_http_and_allows_replay(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    requests: list[str] = []
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        requests.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        posts += 1
        return httpx.Response(200, json={"message": {"id": f"replay-{posts}"}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    database_path = tmp_path / ".chatto-rss-bridge.db"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main([], http_client=client) == 0
        with sqlite3.connect(database_path) as database:
            database.execute("INSERT INTO skipped (guid) VALUES ('deliberate-skip')")
        requests.clear()
        assert main(["--clear-feed"], http_client=client) == 0
        assert requests == []
        assert database_path.is_file()
        with sqlite3.connect(database_path) as database:
            assert database.execute("SELECT guid FROM seen").fetchall() == []
            assert database.execute("SELECT guid FROM skipped").fetchall() == []
        assert main([], http_client=client) == 0

    assert requests == ["GET", "POST"]
    assert posts == 2


def test_clear_feed_refuses_pending_attempt_without_http(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    with sqlite3.connect(database_path) as database:
        database.execute(
            "CREATE TABLE seen (guid TEXT PRIMARY KEY, chatto_message_id TEXT NOT NULL)"
        )
        database.execute("CREATE TABLE skipped (guid TEXT PRIMARY KEY)")
        database.execute(
            "CREATE TABLE pending_attempts (guid TEXT PRIMARY KEY, status TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO seen VALUES ('confirmed-guid', 'chatto-message-1')"
        )
        database.execute(
            "INSERT INTO pending_attempts VALUES ('pending-guid', 'pending')"
        )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=RSS_ITEM)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main(["--clear-feed"], http_client=client)

    assert result == 1
    assert requests == []
    assert "pending" in capsys.readouterr().err
    with sqlite3.connect(database_path) as database:
        confirmed = database.execute("SELECT guid FROM seen").fetchall()
        pending = database.execute("SELECT guid FROM pending_attempts").fetchall()
    assert confirmed == [("confirmed-guid",)]
    assert pending == [("pending-guid",)]


def test_lost_chatto_response_stays_pending_and_is_not_reposted(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    accepted_posts: list[dict[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            return httpx.Response(503)
        if request.url.path.endswith("RoomService/GetRoomEvents"):
            return httpx.Response(403)
        if request.url.path.endswith("MessageService/CreateMessage"):
            accepted_posts.append(json.loads(request.content))
            if len(accepted_posts) == 1:
                raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(200, json={"message": {"id": "duplicate"}})
        raise AssertionError("unexpected Chatto request")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    database_path = tmp_path / ".chatto-rss-bridge.db"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main([], http_client=client) == 1
        with sqlite3.connect(database_path) as database:
            pending = database.execute(
                "SELECT guid, article_link, expected_body, status FROM pending_attempts"
            ).fetchall()
            confirmed = database.execute("SELECT guid FROM seen").fetchall()
        assert pending == [
            (
                "episode-guid-1",
                "https://www.deutschlandfunk.de/example-episode",
                accepted_posts[0]["body"],
                "pending",
            )
        ]
        assert confirmed == []
        capsys.readouterr()
        assert main([], http_client=client) == 1

    assert len(accepted_posts) == 1
    assert "HTTP 403" in capsys.readouterr().err
    with sqlite3.connect(database_path) as database:
        assert database.execute("SELECT guid FROM pending_attempts").fetchall() == [
            ("episode-guid-1",)
        ]


def test_pending_attempt_is_confirmed_from_matching_search_result(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    expected_body = (
        "Presseschau today\n\nA concise summary of today's episode.\n\n"
        "https://www.deutschlandfunk.de/example-episode"
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    _seed_pending_attempt(database_path, expected_body)
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            search_request = json.loads(request.content)
            assert search_request["roomId"] == "room-1"
            assert (
                "https://www.deutschlandfunk.de/example-episode"
                in search_request["query"]
            )
            if "cursor" not in search_request:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "message": {
                                    "id": "untrusted-message",
                                    "roomId": "room-1",
                                    "actorId": "another-user",
                                    "body": expected_body,
                                }
                            }
                        ],
                        "nextCursor": "next-search-page",
                    },
                )
            assert search_request["cursor"] == "next-search-page"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "message": {
                                "id": "existing-message-1",
                                "roomId": "room-1",
                                "actorId": "bot-1",
                                "body": expected_body,
                            }
                        }
                    ]
                },
            )
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        raise AssertionError("reconciliation must not create a duplicate message")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main([], http_client=client) == 0

    assert paths == [
        "/api/connect/chatto.api.v1.ViewerService/GetViewer",
        "/api/connect/chatto.api.v1.MessageSearchService/SearchMessages",
        "/api/connect/chatto.api.v1.MessageSearchService/SearchMessages",
        "/presseschau.xml",
    ]
    with sqlite3.connect(database_path) as database:
        confirmed = database.execute(
            "SELECT guid, chatto_message_id FROM seen"
        ).fetchall()
        pending = database.execute("SELECT guid FROM pending_attempts").fetchall()
    assert confirmed == [("episode-guid-1", "existing-message-1")]
    assert pending == []


def test_timeline_fallback_finds_bot_message_when_search_hit_is_unreliable(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    expected_body = (
        "Presseschau today\n\nA concise summary of today's episode.\n\n"
        "https://www.deutschlandfunk.de/example-episode"
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    _seed_pending_attempt(database_path, expected_body)
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "message": {
                                "id": "untrusted-message",
                                "roomId": "room-1",
                                "actorId": "another-user",
                                "body": expected_body,
                            }
                        }
                    ]
                },
            )
        if request.url.path.endswith("RoomService/GetRoomEvents"):
            return httpx.Response(
                200,
                json={
                    "page": {
                        "events": [
                            {
                                "id": "event-1",
                                "actorId": "bot-1",
                                "messagePosted": {
                                    "message": {
                                        "id": "timeline-message-1",
                                        "roomId": "room-1",
                                        "actorId": "bot-1",
                                        "body": expected_body,
                                    }
                                },
                            }
                        ],
                        "startCursor": "start-1",
                        "endCursor": "end-1",
                        "hasOlder": False,
                        "hasNewer": False,
                    }
                },
            )
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        raise AssertionError("timeline reconciliation must avoid another post")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main([], http_client=client) == 0

    assert paths == [
        "/api/connect/chatto.api.v1.ViewerService/GetViewer",
        "/api/connect/chatto.api.v1.MessageSearchService/SearchMessages",
        "/api/connect/chatto.api.v1.RoomService/GetRoomEvents",
        "/presseschau.xml",
    ]
    with sqlite3.connect(database_path) as database:
        confirmed = database.execute(
            "SELECT guid, chatto_message_id FROM seen"
        ).fetchall()
        pending = database.execute("SELECT guid FROM pending_attempts").fetchall()
    assert confirmed == [("episode-guid-1", "timeline-message-1")]
    assert pending == []


def test_reliable_timeline_absence_allows_retry_after_all_pages(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    expected_body = (
        "Presseschau today\n\nA concise summary of today's episode.\n\n"
        "https://www.deutschlandfunk.de/example-episode"
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    _seed_pending_attempt(database_path, expected_body)
    paths: list[str] = []

    def unrelated_event(message_id: str) -> dict[str, object]:
        return {
            "id": f"event-{message_id}",
            "actorId": "another-user",
            "messagePosted": {
                "message": {
                    "id": message_id,
                    "roomId": "room-1",
                    "actorId": "another-user",
                    "body": "An unrelated message.",
                }
            },
        }

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            return httpx.Response(200, json={"results": []})
        if request.url.path.endswith("RoomService/GetRoomEvents"):
            payload = json.loads(request.content)
            if "cursor" not in payload:
                return httpx.Response(
                    200,
                    json={
                        "page": {
                            "events": [unrelated_event("recent-message")],
                            "startCursor": "recent-start",
                            "endCursor": "recent-end",
                            "hasOlder": True,
                            "hasNewer": False,
                        }
                    },
                )
            assert payload["cursor"] == {"before": "recent-start"}
            return httpx.Response(
                200,
                json={
                    "page": {
                        "events": [unrelated_event("old-message")],
                        "startCursor": "old-start",
                        "endCursor": "old-end",
                        "hasOlder": False,
                        "hasNewer": True,
                    }
                },
            )
        if request.url.path.endswith("MessageService/CreateMessage"):
            assert json.loads(request.content)["body"] == expected_body
            return httpx.Response(200, json={"message": {"id": "retried-message"}})
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        raise AssertionError("unexpected Chatto request")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert main([], http_client=client) == 0

    assert paths == [
        "/api/connect/chatto.api.v1.ViewerService/GetViewer",
        "/api/connect/chatto.api.v1.MessageSearchService/SearchMessages",
        "/api/connect/chatto.api.v1.RoomService/GetRoomEvents",
        "/api/connect/chatto.api.v1.RoomService/GetRoomEvents",
        "/api/connect/chatto.api.v1.MessageService/CreateMessage",
        "/presseschau.xml",
    ]
    with sqlite3.connect(database_path) as database:
        confirmed = database.execute(
            "SELECT guid, chatto_message_id FROM seen"
        ).fetchall()
        pending = database.execute("SELECT guid FROM pending_attempts").fetchall()
    assert confirmed == [("episode-guid-1", "retried-message")]
    assert pending == []


def test_unavailable_search_and_timeline_leave_attempt_pending(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    _seed_pending_attempt(database_path, "Expected pending body")
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            return httpx.Response(503)
        if request.url.path.endswith("RoomService/GetRoomEvents"):
            return httpx.Response(403)
        raise AssertionError("an inconclusive read must never trigger a post")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    assert result == 1
    assert paths == [
        "/api/connect/chatto.api.v1.ViewerService/GetViewer",
        "/api/connect/chatto.api.v1.MessageSearchService/SearchMessages",
        "/api/connect/chatto.api.v1.RoomService/GetRoomEvents",
    ]
    assert "HTTP 403" in capsys.readouterr().err
    with sqlite3.connect(database_path) as database:
        pending = database.execute("SELECT guid FROM pending_attempts").fetchall()
        confirmed = database.execute("SELECT guid FROM seen").fetchall()
    assert pending == [("episode-guid-1",)]
    assert confirmed == []


def test_concurrent_runs_serialize_pending_reconciliation_and_posting(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    database_path = tmp_path / ".chatto-rss-bridge.db"
    _seed_pending_attempt(database_path, "Expected pending body")
    first_post_entered = Event()
    release_first_post = Event()
    second_run_started = Event()
    second_post_entered = Event()
    counter_lock = Lock()
    post_count = 0
    first_post_accepted = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal first_post_accepted, post_count
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        if request.url.path.endswith("ViewerService/GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-1"}}})
        if request.url.path.endswith("MessageSearchService/SearchMessages"):
            with counter_lock:
                accepted = first_post_accepted
            if accepted:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "message": {
                                    "id": "recovered-message",
                                    "roomId": "room-1",
                                    "actorId": "bot-1",
                                    "body": "Expected pending body",
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"results": []})
        if request.url.path.endswith("RoomService/GetRoomEvents"):
            return httpx.Response(
                200,
                json={
                    "page": {
                        "events": [],
                        "hasOlder": False,
                        "hasNewer": False,
                    }
                },
            )
        if request.url.path.endswith("MessageService/CreateMessage"):
            with counter_lock:
                post_count += 1
                current_post = post_count
            if current_post == 1:
                first_post_entered.set()
                if not release_first_post.wait(timeout=5):
                    raise AssertionError("test did not release the first post")
                with counter_lock:
                    first_post_accepted = True
                return httpx.Response(503)
            else:
                second_post_entered.set()
            return httpx.Response(
                200, json={"message": {"id": f"recovered-{current_post}"}}
            )
        raise AssertionError("unexpected request")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:

        def invoke(second: bool = False) -> int:
            if second:
                second_run_started.set()
            return main([], http_client=client)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(invoke)
            assert first_post_entered.wait(timeout=2)
            second = executor.submit(invoke, True)
            assert second_run_started.wait(timeout=2)
            overlapped = second_post_entered.wait(timeout=0.2)
            release_first_post.set()
            results = (first.result(timeout=5), second.result(timeout=5))

    assert not overlapped
    assert results == (1, 0)
    assert post_count == 1


def test_feed_items_are_posted_oldest_first_with_plain_text_descriptions(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    feed = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>New episode</title><link>https://example.com/new</link>
        <description><![CDATA[<p>New <strong>summary</strong>.</p>]]></description>
        <guid>new-guid</guid><pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate>
      </item>
      <item><title>Old episode</title><link>https://example.com/old</link>
        <description><![CDATA[<p>Old <strong>summary</strong>.</p>]]></description>
        <guid>old-guid</guid><pubDate>Wed, 23 Sep 2026 07:05:03 +0200</pubDate>
      </item>
    </channel></rss>"""
    posted_bodies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=feed)
        posted_bodies.append(json.loads(request.content)["body"])
        return httpx.Response(
            200, json={"message": {"id": f"chatto-message-{len(posted_bodies)}"}}
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    assert result == 0
    assert len(posted_bodies) == 2
    assert posted_bodies[0].startswith("Old episode\n\nOld summary.\n\n")
    assert posted_bodies[1].startswith("New episode\n\nNew summary.\n\n")
    assert all("<" not in body and ">" not in body for body in posted_bodies)


def test_rss_document_without_channel_fails_before_posting(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, content=b"<rss version='2.0'/>")
        return httpx.Response(200, json={"message": {"id": "unexpected"}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    assert result == 1
    assert methods == ["GET"]
    assert "channel" in capsys.readouterr().err


def test_database_error_fails_before_fetching_or_posting(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    (tmp_path / ".chatto-rss-bridge.db").mkdir()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=RSS_ITEM)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    assert result == 1
    assert requests == []
    assert "state database" in capsys.readouterr().err


def test_item_missing_guid_fails_before_any_feed_item_is_posted(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    bad_item = """<item><title>Incomplete episode</title>
      <link>https://example.com/incomplete</link>
      <description>Summary</description>
      <pubDate>Wed, 23 Sep 2026 07:05:03 +0200</pubDate>
    </item>"""
    feed = RSS_ITEM.replace("</channel>", bad_item + "</channel>").encode()
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, content=feed)
        return httpx.Response(200, json={"message": {"id": "unexpected"}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    captured = capsys.readouterr()
    assert result == 1
    assert methods == ["GET"]
    assert "guid" in captured.err


def test_denied_chatto_post_fails_without_claiming_success(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=private-test-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        return httpx.Response(403, text="private-test-key denied")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    captured = capsys.readouterr()
    assert result == 1
    assert "HTTP 403" in captured.err
    assert "private-test-key" not in captured.out + captured.err
    assert captured.out == ""
    with sqlite3.connect(tmp_path / ".chatto-rss-bridge.db") as database:
        saved = database.execute("SELECT guid FROM seen").fetchall()
        pending = database.execute(
            "SELECT guid FROM pending_attempts WHERE status = 'pending'"
        ).fetchall()
    assert saved == []
    assert pending == []


def test_chatto_response_without_message_id_is_not_success(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-api-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://feed.example/presseschau.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=RSS_ITEM)
        return httpx.Response(200, json={"message": {}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = main([], http_client=client)

    captured = capsys.readouterr()
    assert result == 1
    assert "message ID" in captured.err
    assert captured.out == ""
    with sqlite3.connect(tmp_path / ".chatto-rss-bridge.db") as database:
        pending = database.execute(
            "SELECT guid, article_link, expected_body, status FROM pending_attempts"
        ).fetchall()
    assert pending == [
        (
            "episode-guid-1",
            "https://www.deutschlandfunk.de/example-episode",
            """Presseschau today

A concise summary of today's episode.

https://www.deutschlandfunk.de/example-episode""",
            "pending",
        )
    ]
