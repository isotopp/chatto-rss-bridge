import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from chatto_rss_bridge.commands import handle_message
from chatto_rss_bridge.config import Config
from chatto_rss_bridge.state import FeedStore

FEED_URL = "https://feed.example.test/news.xml"


def _config(path: Path) -> Config:
    return Config(
        api_key="test-api-key",
        room_id="room-1",
        rss_source="https://legacy.example.test/feed.xml",
        chatto_base_url="https://chatto.example.test",
        state_path=path,
    )


def _event(*, thread_root: str = "") -> dict[str, object]:
    posted: dict[str, object] = {
        "roomId": "room-1",
        "bodyPlaintext": "@rss-bot list",
        "mentions": [{"direct": {"userId": "bot-user"}, "includesViewer": True}],
    }
    if thread_root:
        posted["threadRootEventId"] = thread_root
    return {
        "id": "command-event-id",
        "actorId": "operator-user",
        "messagePosted": posted,
    }


def _body_event(body: str, *, thread_root: str = "") -> dict[str, object]:
    event = _event(thread_root=thread_root)
    posted = event["messagePosted"]
    assert isinstance(posted, dict)
    posted["bodyPlaintext"] = body
    return event


def test_list_command_replies_in_the_message_thread(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": {"id": "reply-message-id"}})

    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", "https://feed.example.test/rss", 20)
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            handled = handle_message(
                client, config, store, bot_user_id="bot-user", event=_event()
            )

        assert handled is True
        assert len(requests) == 1
        request = requests[0]
        assert (
            request.url.path
            == "/api/connect/chatto.api.v1.MessageService/CreateMessage"
        )
        assert request.headers["Authorization"] == "Bearer test-api-key"
        reply = json.loads(request.content)
        assert reply["roomId"] == "room-1"
        assert reply["threadRootEventId"] == "command-event-id"
        assert reply["inReplyTo"] == "command-event-id"
        assert "briefing" in reply["body"]
        assert "https://feed.example.test/rss" in reply["body"]
        assert "20" in reply["body"]
    finally:
        store.close()


def test_command_in_existing_thread_replies_to_that_root(tmp_path: Path) -> None:
    request_body: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"id": "reply-message-id"}})

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            handled = handle_message(
                client,
                config,
                store,
                bot_user_id="bot-user",
                event=_body_event("@rss-bot help", thread_root="thread-root-id"),
            )
        assert handled
        assert request_body["threadRootEventId"] == "thread-root-id"
        assert request_body["inReplyTo"] == "command-event-id"
    finally:
        store.close()


def test_unrelated_and_non_post_events_are_ignored(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": {"id": "unexpected"}})

    base = _body_event("@rss-bot help")
    posted = base["messagePosted"]
    assert isinstance(posted, dict)
    own_message = json.loads(json.dumps(base))
    own_message["actorId"] = "bot-user"
    wrong_room = json.loads(json.dumps(base))
    wrong_room["messagePosted"]["roomId"] = "other-room"
    no_mention = json.loads(json.dumps(base))
    no_mention["messagePosted"]["mentions"] = []
    mention_not_included = json.loads(json.dumps(base))
    mention_not_included["messagePosted"]["mentions"][0]["includesViewer"] = False
    echo = json.loads(json.dumps(base))
    echo["messagePosted"]["echoOfEventId"] = "original-event"
    edited = {"id": "edited-event", "messageEdited": {"roomId": "room-1"}}
    missing_body = json.loads(json.dumps(base))
    del missing_body["messagePosted"]["bodyPlaintext"]

    store = FeedStore(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            for event in (
                own_message,
                wrong_room,
                no_mention,
                mention_not_included,
                echo,
                edited,
                missing_body,
            ):
                assert (
                    handle_message(
                        client,
                        _config(tmp_path / "state.db"),
                        store,
                        bot_user_id="bot-user",
                        event=event,
                    )
                    is False
                )
        assert requests == []
    finally:
        store.close()


def test_help_and_exact_argument_counts_return_usage_in_thread(tmp_path: Path) -> None:
    replies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"id": f"reply-{len(replies)}"}})

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert handle_message(
                client,
                config,
                store,
                bot_user_id="bot-user",
                event=_body_event("@rss-bot help"),
            )
            extra_arg = _body_event("@rss-bot help extra")
            extra_arg["id"] = "second-command"
            assert handle_message(
                client, config, store, bot_user_id="bot-user", event=extra_arg
            )
        assert "add <feedname> <url> <minutes>" in replies[0]["body"]
        assert replies[1]["body"].startswith("Usage: help")
        assert replies[0]["inReplyTo"] == "command-event-id"
        assert replies[1]["inReplyTo"] == "second-command"
    finally:
        store.close()


def test_delete_command_removes_feed_and_reports_unknown_name(tmp_path: Path) -> None:
    replies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": f"reply-{len(replies)}"}})

    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", "https://feed.example.test/rss", 20)
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert handle_message(
                client,
                config,
                store,
                bot_user_id="bot-user",
                event=_body_event("@rss-bot delete briefing"),
            )
            unknown = _body_event("@rss-bot delete missing")
            unknown["id"] = "unknown-command"
            assert handle_message(
                client, config, store, bot_user_id="bot-user", event=unknown
            )
        assert store.list_feeds() == []
        assert replies == ["Deleted feed briefing.", "No feed named missing."]
    finally:
        store.close()


def test_add_command_posts_proof_then_replies_in_command_thread(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    feed_xml = b"""<rss version="2.0"><channel><item>
      <title>Newest article</title><link>https://example.test/new</link>
      <description>Newest summary.</description><guid>new-guid</guid>
      <pubDate>Thu, 24 Sep 2026 07:05:03 +0200</pubDate>
    </item></channel></rss>"""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=feed_xml)
        body = json.loads(request.content)
        requests.append(body)
        message_id = "reply-id" if "threadRootEventId" in body else "proof-id"
        return httpx.Response(200, json={"message": {"id": message_id}})

    store = FeedStore(tmp_path / "state.db")
    config = _config(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            event = _body_event(
                f"@rss-bot add briefing {FEED_URL} 15",
                thread_root="thread-root-id",
            )
            assert handle_message(
                client, config, store, bot_user_id="bot-user", event=event
            )
        assert len(requests) == 2
        assert requests[0]["body"].startswith("Newest article")
        assert "threadRootEventId" not in requests[0]
        assert requests[1]["threadRootEventId"] == "thread-root-id"
        assert requests[1]["inReplyTo"] == "command-event-id"
        assert requests[1]["body"] == "Added briefing; proof post proof-id confirmed"
        assert store.list_feeds()[0].interval_minutes == 15
        assert store.contains("briefing", "new-guid")
    finally:
        store.close()


def test_delete_command_refuses_feed_with_uncertain_post(tmp_path: Path) -> None:
    replies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": "reply-id"}})

    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", "https://feed.example.test/rss", 20)
    store.begin_attempt(
        "briefing", "pending-guid", "https://example.test/article", "Article"
    )
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert handle_message(
                client,
                _config(tmp_path / "state.db"),
                store,
                bot_user_id="bot-user",
                event=_body_event("@rss-bot delete briefing"),
            )
        assert store.list_feeds()[0].name == "briefing"
        assert replies == [
            "Cannot delete briefing while one of its posts is uncertain."
        ]
    finally:
        store.close()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("@rss-bot add briefing https://feed.example/rss", "Usage: add"),
        ("@rss-bot list extra", "Usage: list"),
        ("@rss-bot delete", "Usage: delete"),
    ],
)
def test_commands_require_exact_argument_counts(
    tmp_path: Path, body: str, expected: str
) -> None:
    replies: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content)["body"])
        return httpx.Response(200, json={"message": {"id": "reply-id"}})

    store = FeedStore(tmp_path / "state.db")
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            assert handle_message(
                client,
                _config(tmp_path / "state.db"),
                store,
                bot_user_id="bot-user",
                event=_body_event(body),
            )
        assert len(replies) == 1
        assert replies[0].startswith(expected)
        assert store.list_feeds() == []
    finally:
        store.close()
