from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .chatto import ChattoError, ReconciliationError, get_viewer_id
from .commands import handle_message
from .config import Config, ConfigError
from .feed_service import check_due_feeds
from .realtime_pb2 import (
    RealtimeCloseCode,
    RealtimeInitialState,
    RealtimeRecovery,
    RealtimeServerFrame,
    RealtimeSubscribe,
)
from .state import FeedStore, StateError

_LOG = logging.getLogger(__name__)
_POLL_SECONDS = 30
_MAX_BACKOFF_SECONDS = 60


class RealtimeServiceError(RuntimeError):
    pass


class _ReconnectRequested(Exception):
    def __init__(self, delay: float | None = None) -> None:
        self.delay = delay


@dataclass
class _Resources:
    client: httpx.Client
    store: FeedStore
    owns_client: bool


async def run_service(
    config: Config,
    *,
    http_client: httpx.Client | None = None,
    shutdown_event: asyncio.Event | None = None,
    websocket_connector: Callable[..., Any] = connect,
) -> None:
    """Listen for Chatto commands and poll saved feeds until shutdown."""
    loop = asyncio.get_running_loop()
    shutdown = shutdown_event or asyncio.Event()
    _install_shutdown_handlers(loop, shutdown)
    # ponytail: one worker keeps SQLite on its owning thread; add more only if throughput matters.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chatto-rss-bridge")
    resources: _Resources | None = None
    tasks: list[asyncio.Task[Any]] = []
    try:
        resources = await loop.run_in_executor(
            executor, _open_resources, config, http_client
        )
        bot_user_id = await loop.run_in_executor(
            executor, get_viewer_id, resources.client, config
        )
        listener = asyncio.create_task(
            _listen(
                config,
                resources,
                bot_user_id,
                executor,
                shutdown,
                websocket_connector,
            )
        )
        scheduler = asyncio.create_task(
            _schedule(config, resources, executor, shutdown)
        )
        stop_waiter = asyncio.create_task(shutdown.wait())
        tasks = [listener, scheduler, stop_waiter]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if not shutdown.is_set():
            for task in done:
                await task
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            if resources is not None:
                await loop.run_in_executor(executor, _close_resources, resources)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)


async def _listen(
    config: Config,
    resources: _Resources,
    bot_user_id: str,
    executor: ThreadPoolExecutor,
    shutdown: asyncio.Event,
    websocket_connector: Callable[..., Any],
) -> None:
    loop = asyncio.get_running_loop()
    delay = 1.0
    uri = _realtime_url(config)
    while not shutdown.is_set():
        cursor = await loop.run_in_executor(executor, resources.store.resume_cursor)
        had_cursor = cursor is not None
        try:
            async with websocket_connector(
                uri,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=5 * 1024 * 1024,
            ) as websocket:
                request = RealtimeSubscribe(
                    protocol_version=4,
                    bearer_token=config.api_key,
                    initial_state=RealtimeInitialState.REALTIME_INITIAL_STATE_LIVE_ONLY,
                )
                if cursor is not None:
                    request.resume_cursor = cursor
                await websocket.send(request.SerializeToString())
                async for raw in websocket:
                    if not isinstance(raw, bytes):
                        raise RealtimeServiceError(
                            "Chatto realtime sent a non-binary frame"
                        )
                    try:
                        frame = RealtimeServerFrame.FromString(raw)
                    except DecodeError as exc:
                        raise RealtimeServiceError(
                            "Chatto realtime sent an invalid protobuf frame"
                        ) from exc
                    delay = await _process_frame(
                        frame,
                        config,
                        resources,
                        bot_user_id,
                        executor,
                        had_cursor=had_cursor,
                    )
                    if shutdown.is_set():
                        return
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
        except _ReconnectRequested as reconnect:
            if reconnect.delay is not None:
                delay = min(max(reconnect.delay, 0.1), _MAX_BACKOFF_SECONDS)
            else:
                delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
        except (OSError, TimeoutError, WebSocketException) as exc:
            _LOG.warning("Chatto realtime disconnected: %s", exc)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
        except RealtimeServiceError:
            raise
        if not shutdown.is_set():
            await _wait_or_shutdown(shutdown, delay)


async def _process_frame(
    frame: RealtimeServerFrame,
    config: Config,
    resources: _Resources,
    bot_user_id: str,
    executor: ThreadPoolExecutor,
    *,
    had_cursor: bool,
) -> float:
    loop = asyncio.get_running_loop()
    frame_kind = frame.WhichOneof("frame")
    if frame_kind == "event":
        event = frame.event
        if event.WhichOneof("event") == "message_posted":
            decoded = MessageToDict(event)
            try:
                await loop.run_in_executor(
                    executor,
                    partial(
                        handle_message,
                        resources.client,
                        config,
                        resources.store,
                        bot_user_id=bot_user_id,
                        event=decoded,
                    ),
                )
            except ChattoError as exc:
                _LOG.error(
                    "Could not finish Chatto command event %s: %s", event.id, exc
                )
        if event.HasField("cursor"):
            await loop.run_in_executor(
                executor, resources.store.save_resume_cursor, event.cursor
            )
    elif frame_kind == "heartbeat":
        if frame.heartbeat.HasField("cursor"):
            await loop.run_in_executor(
                executor,
                resources.store.save_resume_cursor,
                frame.heartbeat.cursor,
            )
    elif frame_kind == "caught_up":
        caught_up = frame.caught_up
        if (
            had_cursor
            and caught_up.recovery != RealtimeRecovery.REALTIME_RECOVERY_RESUMED
        ):
            _LOG.warning(
                "Chatto could not resume the saved cursor; room commands during "
                "the gap may have been missed (recovery=%s)",
                caught_up.recovery,
            )
        if caught_up.cursor:
            await loop.run_in_executor(
                executor, resources.store.save_resume_cursor, caught_up.cursor
            )
        return 1.0
    elif frame_kind == "close":
        close = frame.close
        if close.code == RealtimeCloseCode.REALTIME_CLOSE_CODE_RESYNC_REQUIRED:
            await loop.run_in_executor(executor, resources.store.clear_resume_cursor)
            _LOG.warning(
                "Chatto could not resume the saved cursor; room commands during "
                "the gap may have been missed"
            )
        if not close.reconnect:
            raise RealtimeServiceError(
                f"Chatto requested a permanent realtime close: {close.message}"
            )
        retry_after = None
        if close.HasField("retry_after"):
            retry_after = close.retry_after.seconds + close.retry_after.nanos / 1e9
        raise _ReconnectRequested(retry_after)
    return 1.0


async def _schedule(
    config: Config,
    resources: _Resources,
    executor: ThreadPoolExecutor,
    shutdown: asyncio.Event,
) -> None:
    loop = asyncio.get_running_loop()
    while not shutdown.is_set():
        try:
            outcomes = await loop.run_in_executor(
                executor, check_due_feeds, resources.client, config, resources.store
            )
            for name, error in outcomes.items():
                if error is not None:
                    _LOG.error("RSS check failed for feed %s: %s", name, error)
        except StateError as exc:
            _LOG.error("Could not schedule RSS checks: %s", exc)
        await _wait_or_shutdown(shutdown, _POLL_SECONDS)


async def _wait_or_shutdown(shutdown: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)
    except TimeoutError:
        pass


def _realtime_url(config: Config) -> str:
    base = urlsplit(config.chatto_base_url)
    scheme = "wss" if base.scheme == "https" else "ws"
    return urlunsplit((scheme, base.netloc, "/api/realtime", "", ""))


def _open_resources(config: Config, http_client: httpx.Client | None) -> _Resources:
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=15.0)
    try:
        return _Resources(client, FeedStore(config.state_path), owns_client)
    except BaseException:
        if owns_client:
            client.close()
        raise


def _close_resources(resources: _Resources) -> None:
    resources.store.close()
    if resources.owns_client:
        resources.client.close()


def _install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event
) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError, RuntimeError:
            pass


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_service(Config.load()))
    except KeyboardInterrupt:
        return 0
    except (
        ChattoError,
        ConfigError,
        RealtimeServiceError,
        ReconciliationError,
        StateError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
