import json
import sqlite3
from datetime import datetime, tzinfo
from pathlib import Path
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
    assert saved == []


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
