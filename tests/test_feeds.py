import json
from pathlib import Path

import httpx
import pytest

from chatto_rss_bridge.chatto import RejectedChattoError, UncertainChattoError
from chatto_rss_bridge.config import Config
from chatto_rss_bridge.feed_service import add_feed, check_due_feeds
from chatto_rss_bridge.reconciliation import ReconciliationError
from chatto_rss_bridge.rss import FeedError, fetch_episodes
from chatto_rss_bridge.state import FeedExistsError, FeedStore

FEED_URL = "https://feed.example.test/news.xml"
FEED_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Newest article</title><link>https://example.test/new</link>
    <description>Newest summary.</description><guid>new-guid</guid>
    <pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate></item>
  <item><title>Older article</title><link>https://example.test/old</link>
    <description>Older summary.</description><guid>old-guid</guid>
    <pubDate>Wed, 23 Sep 2026 07:05:03 +0200</pubDate></item>
</channel></rss>"""


def _config(path: Path) -> Config:
    return Config(
        api_key="test-api-key",
        room_id="room-1",
        rss_source="https://legacy.example.test/feed.xml",
        chatto_base_url="https://chatto.example.test",
        state_path=path,
        bot_bridge_role="rss-bot-operator",
    )


def test_adding_feed_posts_newest_item_and_marks_initial_snapshot_seen(
    tmp_path: Path,
) -> None:
    posted_bodies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == FEED_URL
            return httpx.Response(200, content=FEED_XML)
        posted_bodies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": "proof-message-id"}})

    store = FeedStore(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            add_feed(
                client,
                _config(tmp_path / "state.db"),
                store,
                name="briefing",
                url=FEED_URL,
                interval_minutes=15,
            )

        assert [body.splitlines()[0] for body in posted_bodies] == ["Newest article"]
        assert store.list_feeds()[0].name == "briefing"
        assert store.list_feeds()[0].interval_minutes == 15
        assert store.contains("briefing", "new-guid")
        assert store.contains("briefing", "old-guid")
        assert store.pending_attempts("briefing") == []
    finally:
        store.close()


def test_feed_item_without_description_posts_title_and_link(tmp_path: Path) -> None:
    feed = FEED_XML.replace(b"<description>Newest summary.</description>", b"")
    posted_bodies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=feed)
        posted_bodies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": "proof-message-id"}})

    store = FeedStore(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            add_feed(
                client,
                _config(tmp_path / "state.db"),
                store,
                name="briefing",
                url=FEED_URL,
                interval_minutes=15,
            )
        assert posted_bodies == ["Newest article\n\nhttps://example.test/new"]
        assert store.contains("briefing", "new-guid")
    finally:
        store.close()


@pytest.mark.parametrize(
    ("name", "url", "interval_minutes", "body"),
    [
        ("bad name", FEED_URL, 15, FEED_XML),
        ("briefing", "ftp://feed.example.test/rss", 15, FEED_XML),
        ("briefing", FEED_URL, 9, FEED_XML),
        ("briefing", FEED_URL, 9_223_372_036_854_775_808, FEED_XML),
        ("briefing", FEED_URL, 15, b"<rss"),
        ("briefing", FEED_URL, 15, b"<feed/>"),
        ("briefing", FEED_URL, 15, b"<rss version='2.0'><channel/></rss>"),
    ],
)
def test_invalid_or_empty_feed_does_not_activate_or_post(
    tmp_path: Path, name: str, url: str, interval_minutes: int, body: bytes
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=body)
        return httpx.Response(200, json={"message": {"id": "unexpected"}})

    store = FeedStore(tmp_path / "state.db")
    try:
        with (
            httpx.Client(transport=httpx.MockTransport(handle)) as client,
            pytest.raises(FeedError),
        ):
            add_feed(
                client,
                _config(tmp_path / "state.db"),
                store,
                name=name,
                url=url,
                interval_minutes=interval_minutes,
            )
        assert store.list_feeds() == []
        assert store.pending_attempts() == []
        assert all(request.method == "GET" for request in requests)
    finally:
        store.close()


def test_rejected_proof_post_does_not_activate_feed(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=FEED_XML)
        return httpx.Response(403)

    store = FeedStore(tmp_path / "state.db")
    try:
        with (
            httpx.Client(transport=httpx.MockTransport(handle)) as client,
            pytest.raises(RejectedChattoError),
        ):
            add_feed(
                client,
                _config(tmp_path / "state.db"),
                store,
                name="briefing",
                url=FEED_URL,
                interval_minutes=15,
            )
        assert store.list_feeds() == []
        assert store.pending_attempts() == []
    finally:
        store.close()


def test_repeated_add_after_lost_confirmation_reconciles_without_duplicate_post(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    body = "Newest article\n\nNewest summary.\n\nhttps://example.test/new"

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=FEED_XML)
        if request.url.path.endswith("CreateMessage"):
            return httpx.Response(200, json={"message": {}})
        if request.url.path.endswith("GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-user"}}})
        if request.url.path.endswith("SearchMessages"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "message": {
                                "id": "proof-message-id",
                                "roomId": "room-1",
                                "actorId": "bot-user",
                                "body": body,
                            }
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url.path}")

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(UncertainChattoError):
                add_feed(
                    client,
                    config,
                    store,
                    name="briefing",
                    url=FEED_URL,
                    interval_minutes=15,
                )
            with pytest.raises(FeedExistsError):
                add_feed(
                    client,
                    config,
                    store,
                    name="briefing",
                    url=FEED_URL,
                    interval_minutes=30,
                )
            add_feed(
                client,
                config,
                store,
                name="briefing",
                url=FEED_URL,
                interval_minutes=15,
            )

        assert (
            sum(request.url.path.endswith("CreateMessage") for request in requests) == 1
        )
        assert store.list_feeds()[0].name == "briefing"
        assert store.contains("briefing", "new-guid")
        assert store.contains("briefing", "old-guid")
        assert store.pending_attempts("briefing") == []
    finally:
        store.close()


def test_duplicate_active_feed_add_is_rejected_without_another_proof_post(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=FEED_XML)
        return httpx.Response(200, json={"message": {"id": "proof-message-id"}})

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            add_feed(
                client,
                config,
                store,
                name="briefing",
                url=FEED_URL,
                interval_minutes=15,
            )
            with pytest.raises(FeedExistsError):
                add_feed(
                    client,
                    config,
                    store,
                    name="briefing",
                    url=FEED_URL,
                    interval_minutes=15,
                )
        assert len(requests) == 2
    finally:
        store.close()


def test_uncertain_add_stays_pending_when_reconciliation_reads_fail(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=FEED_XML)
        if request.url.path.endswith("CreateMessage"):
            return httpx.Response(200, json={"message": {}})
        if request.url.path.endswith("GetViewer"):
            return httpx.Response(200, json={"user": {"profile": {"id": "bot-user"}}})
        return httpx.Response(503)

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(UncertainChattoError):
                add_feed(
                    client,
                    config,
                    store,
                    name="briefing",
                    url=FEED_URL,
                    interval_minutes=15,
                )
            with pytest.raises(ReconciliationError):
                add_feed(
                    client,
                    config,
                    store,
                    name="briefing",
                    url=FEED_URL,
                    interval_minutes=15,
                )
        assert (
            sum(request.url.path.endswith("CreateMessage") for request in requests) == 1
        )
        assert store.list_feeds() == []
        assert len(store.pending_attempts("briefing")) == 1
    finally:
        store.close()


def test_rss_response_larger_than_limit_is_rejected(monkeypatch) -> None:
    from chatto_rss_bridge import rss

    monkeypatch.setattr(rss, "MAX_FEED_BYTES", 10)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 11))
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(FeedError, match="too large"),
    ):
        fetch_episodes(client, FEED_URL)


def test_due_feeds_keep_overlapping_guids_and_intervals_independent(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    config = _config(state_path)
    store = FeedStore(state_path)
    store.add_feed("alpha", "https://feed.example.test/a.xml", 10)
    store.add_feed("beta", "https://feed.example.test/b.xml", 20)
    posted: list[str] = []
    fetched: list[str] = []
    xml = b"""<rss version="2.0"><channel><item>
      <title>Shared GUID</title><link>https://example.test/shared</link>
      <description>Same GUID in two feeds.</description><guid>shared-guid</guid>
      <pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate>
    </item></channel></rss>"""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            fetched.append(str(request.url))
            return httpx.Response(200, content=xml)
        posted.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": f"message-{len(posted)}"}})

    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert check_due_feeds(client, config, store, now=1_000) == {
                "alpha": None,
                "beta": None,
            }
        assert len(posted) == 2
        assert store.contains("alpha", "shared-guid")
        assert store.contains("beta", "shared-guid")
    finally:
        store.close()

    reopened = FeedStore(state_path)
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert check_due_feeds(client, config, reopened, now=1_599) == {}
            assert check_due_feeds(client, config, reopened, now=1_600) == {
                "alpha": None
            }
        assert fetched == [
            "https://feed.example.test/a.xml",
            "https://feed.example.test/b.xml",
            "https://feed.example.test/a.xml",
        ]
        assert len(posted) == 2
    finally:
        reopened.close()


def test_failed_feed_does_not_stop_others_and_is_retried_after_its_interval(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.db"
    config = _config(state_path)
    store = FeedStore(state_path)
    store.add_feed("alpha", "https://feed.example.test/a.xml", 10)
    store.add_feed("beta", "https://feed.example.test/b.xml", 20)
    checked: list[str] = []
    xml = b"""<rss version="2.0"><channel><item>
      <title>Healthy article</title><link>https://example.test/healthy</link>
      <description>Healthy summary.</description><guid>healthy-guid</guid>
      <pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate>
    </item></channel></rss>"""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            checked.append(str(request.url))
            if request.url.path.endswith("a.xml"):
                return httpx.Response(503)
            return httpx.Response(200, content=xml)
        return httpx.Response(200, json={"message": {"id": "healthy-message"}})

    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            first = check_due_feeds(client, config, store, now=1_000)
            assert first["alpha"] is not None
            assert first["beta"] is None
            assert check_due_feeds(client, config, store, now=1_599) == {}
            second = check_due_feeds(client, config, store, now=1_600)
        assert second["alpha"] is not None
        assert checked == [
            "https://feed.example.test/a.xml",
            "https://feed.example.test/b.xml",
            "https://feed.example.test/a.xml",
        ]
        assert store.contains("beta", "healthy-guid")
        assert not store.contains("alpha", "healthy-guid")
    finally:
        store.close()


def test_poll_posts_unseen_items_oldest_first(tmp_path: Path) -> None:
    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", FEED_URL, 10)
    posted: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=FEED_XML)
        posted.append(json.loads(request.content)["body"].splitlines()[0])
        return httpx.Response(200, json={"message": {"id": f"message-{len(posted)}"}})

    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert check_due_feeds(
                client, _config(tmp_path / "state.db"), store, now=1_000
            ) == {"briefing": None}
        assert posted == ["Older article", "Newest article"]
    finally:
        store.close()
