import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from chatto_rss_bridge.config import Config
from chatto_rss_bridge.realtime_pb2 import (
    RealtimeCaughtUp,
    RealtimeHeartbeat,
    RealtimeRecovery,
    RealtimeServerFrame,
    RealtimeSubscribe,
)
from chatto_rss_bridge.service import run_service
from chatto_rss_bridge.state import FeedStore


def _config(path: Path) -> Config:
    return Config(
        api_key="test-api-key",
        room_id="room-1",
        rss_source="https://legacy.example.test/feed.xml",
        chatto_base_url="https://chatto.example.test",
        state_path=path,
        bot_bridge_role="rss-bot-operator",
    )


def _command_frame() -> bytes:
    fixture = Path(__file__).parent / "fixtures/chatto_realtime_mention.hex"
    return bytes.fromhex(fixture.read_text(encoding="ascii").strip())


def _caught_up(cursor: str, recovery: int) -> bytes:
    return RealtimeServerFrame(
        caught_up=RealtimeCaughtUp(cursor=cursor, recovery=recovery)
    ).SerializeToString()


def _heartbeat(cursor: str) -> bytes:
    return RealtimeServerFrame(
        heartbeat=RealtimeHeartbeat(cursor=cursor)
    ).SerializeToString()


class _FakeConnection:
    def __init__(
        self,
        frames: list[bytes],
        requests: list[RealtimeSubscribe],
        payloads: list[bytes],
        *,
        on_end: Callable[[], None] | None = None,
        wait_after_frames: bool = False,
    ) -> None:
        self.frames = frames
        self.requests = requests
        self.payloads = payloads
        self.on_end = on_end
        self.wait_after_frames = wait_after_frames
        self._ended = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def send(self, payload: bytes) -> None:
        self.payloads.append(payload)
        self.requests.append(RealtimeSubscribe.FromString(payload))

    def __aiter__(self) -> _FakeConnection:
        return self

    async def __anext__(self) -> bytes:
        if self.frames:
            return self.frames.pop(0)
        if not self._ended:
            self._ended = True
            if self.on_end is not None:
                self.on_end()
        if self.wait_after_frames:
            await asyncio.Future()
        raise StopAsyncIteration


class _Connector:
    def __init__(
        self,
        frame_sets: list[list[bytes]],
        *,
        on_second_end: Callable[[], None] | None = None,
    ) -> None:
        self.frame_sets = frame_sets
        self.requests: list[RealtimeSubscribe] = []
        self.payloads: list[bytes] = []
        self.on_second_end = on_second_end
        self.urls: list[str] = []

    def __call__(self, uri: str, **kwargs: Any) -> _FakeConnection:
        del kwargs
        self.urls.append(uri)
        index = len(self.urls) - 1
        return _FakeConnection(
            self.frame_sets[index],
            self.requests,
            self.payloads,
            on_end=self.on_second_end if index == 1 else None,
            wait_after_frames=index == 1,
        )


def test_service_resumes_after_disconnect_and_does_not_repeat_command(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "state.db"
        store = FeedStore(path)
        store.add_feed("briefing", "https://feed.example.test/rss", 10)
        store.close()
        second_replay_processed = asyncio.Event()
        connector = _Connector(
            [
                [
                    _caught_up(
                        "initial-cursor", RealtimeRecovery.REALTIME_RECOVERY_LIVE_ONLY
                    ),
                    _command_frame(),
                    _heartbeat("heartbeat-cursor"),
                ],
                [
                    _command_frame(),
                    _caught_up(
                        "resumed-cursor", RealtimeRecovery.REALTIME_RECOVERY_RESUMED
                    ),
                ],
            ],
            on_second_end=second_replay_processed.set,
        )
        requests: list[httpx.Request] = []

        def http_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("ViewerService/GetViewer"):
                return httpx.Response(
                    200, json={"user": {"profile": {"id": "bot-user"}}}
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=b"""<rss version="2.0"><channel><item>
                      <title>Newest article</title>
                      <link>https://example.test/new</link>
                      <description>Summary</description><guid>new-guid</guid>
                      <pubDate>Fri, 25 Sep 2026 10:00:00 +0200</pubDate>
                    </item></channel></rss>""",
                )
            if request.url.path.endswith("MessageService/CreateMessage"):
                return httpx.Response(200, json={"message": {"id": "reply-id"}})
            raise AssertionError(f"unexpected request: {request.url}")

        shutdown = asyncio.Event()
        with httpx.Client(transport=httpx.MockTransport(http_handler)) as client:
            task = asyncio.create_task(
                run_service(
                    _config(path),
                    http_client=client,
                    shutdown_event=shutdown,
                    websocket_connector=connector,
                )
            )
            await asyncio.wait_for(second_replay_processed.wait(), timeout=5)
            shutdown.set()
            await asyncio.wait_for(task, timeout=3)

        assert connector.urls == ["wss://chatto.example.test/api/realtime"] * 2
        assert len(connector.requests) == 2
        assert connector.requests[0].protocol_version == 4
        assert connector.requests[0].bearer_token == "test-api-key"
        assert connector.requests[0].initial_state == 1
        assert not connector.requests[0].HasField("resume_cursor")
        assert connector.payloads[0] == bytes.fromhex(
            "0804120c746573742d6170692d6b65792001"
        )
        assert connector.requests[1].resume_cursor == "heartbeat-cursor"
        assert connector.payloads[1] == bytes.fromhex(
            "0804120c746573742d6170692d6b65791a106865617274626561742d637572736f722001"
        )
        message_bodies = [
            json.loads(request.content)
            for request in requests
            if request.url.path.endswith("MessageService/CreateMessage")
        ]
        assert (
            sum(
                request.url.path.endswith("MessageService/CreateMessage")
                for request in requests
            )
            == 2
        )
        assert any("threadRootEventId" not in body for body in message_bodies)
        assert any(
            body.get("threadRootEventId") == "command-event-id"
            for body in message_bodies
        )
        store = FeedStore(path)
        try:
            assert store.resume_cursor() == "resumed-cursor"
            assert not store.claim_command("command-event-id")
            assert store.contains("briefing", "new-guid")
        finally:
            store.close()

    asyncio.run(scenario())


def test_service_reports_when_expired_cursor_falls_back_to_live_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        path = tmp_path / "state.db"
        store = FeedStore(path)
        store.save_resume_cursor("expired-cursor")
        store.close()
        second_recovery_processed = asyncio.Event()
        close = RealtimeServerFrame()
        close.close.code = 6
        close.close.message = "cursor expired"
        close.close.reconnect = True
        connector = _Connector(
            [
                [close.SerializeToString()],
                [
                    _caught_up(
                        "fresh-cursor", RealtimeRecovery.REALTIME_RECOVERY_LIVE_ONLY
                    )
                ],
            ],
            on_second_end=second_recovery_processed.set,
        )

        def http_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("ViewerService/GetViewer"):
                return httpx.Response(
                    200, json={"user": {"profile": {"id": "bot-user"}}}
                )
            raise AssertionError(f"unexpected request: {request.url}")

        shutdown = asyncio.Event()
        with httpx.Client(transport=httpx.MockTransport(http_handler)) as client:
            task = asyncio.create_task(
                run_service(
                    _config(path),
                    http_client=client,
                    shutdown_event=shutdown,
                    websocket_connector=connector,
                )
            )
            await asyncio.wait_for(second_recovery_processed.wait(), timeout=5)
            shutdown.set()
            await asyncio.wait_for(task, timeout=3)

        assert len(connector.requests) == 2
        assert connector.requests[0].resume_cursor == "expired-cursor"
        assert not connector.requests[1].HasField("resume_cursor")
        reopened = FeedStore(path)
        try:
            assert reopened.resume_cursor() == "fresh-cursor"
        finally:
            reopened.close()

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    assert "could not resume" in caplog.text
