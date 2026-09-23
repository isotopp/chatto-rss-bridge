import json
from pathlib import Path

import httpx

from chatto_rss_bridge import main

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
