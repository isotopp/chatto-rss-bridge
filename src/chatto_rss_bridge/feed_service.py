from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import httpx

from .chatto import (
    ChattoError,
    ReconciliationError,
    RejectedChattoError,
    post_root_message,
)
from .config import Config
from .reconciliation import reconcile_pending
from .rss import FeedError, fetch_episodes
from .state import (
    Feed,
    FeedExistsError,
    FeedNotFoundError,
    FeedPendingAttempt,
    FeedStore,
    StateError,
)

_FEED_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def add_feed(
    client: httpx.Client,
    config: Config,
    store: FeedStore,
    *,
    name: str,
    url: str,
    interval_minutes: int,
) -> str:
    _validate_feed_input(name, url, interval_minutes)
    try:
        existing = store.get_feed(name)
    except FeedNotFoundError:
        episodes = fetch_episodes(client, url)
        if not episodes:
            raise FeedError("RSS feed contains no articles")
        latest = max(episodes, key=lambda episode: episode.published_at)
        body = "\n\n".join(
            filter(None, (latest.title, latest.description, latest.link))
        )
        attempt = FeedPendingAttempt(name, latest.guid, latest.link, body)
        store.prepare_feed(
            name,
            url,
            interval_minutes,
            [episode.guid for episode in episodes],
            latest.guid,
            latest.link,
            body,
        )
        return _finish_add(client, config, store, attempt, reconcile_first=False)

    if existing.active:
        raise FeedExistsError(f"feed already exists: {name}")
    if existing.url != url or existing.interval_minutes != interval_minutes:
        raise FeedExistsError(
            f"feed add is already pending with different settings: {name}"
        )
    pending = store.pending_attempts(name)
    if len(pending) != 1:
        raise StateError("feed has no unique pending proof post")
    return _finish_add(client, config, store, pending[0], reconcile_first=True)


def check_due_feeds(
    client: httpx.Client,
    config: Config,
    store: FeedStore,
    *,
    now: float | None = None,
) -> dict[str, str | None]:
    checked_at = time.time() if now is None else now
    outcomes: dict[str, str | None] = {}
    for feed in store.due_feeds(checked_at):
        try:
            _check_feed(client, config, store, feed)
            outcomes[feed.name] = None
        except (FeedError, ChattoError, StateError, ReconciliationError) as exc:
            outcomes[feed.name] = str(exc)
        finally:
            completed_at = checked_at if now is not None else time.time()
            store.mark_checked(feed.name, completed_at)
    return outcomes


def _check_feed(
    client: httpx.Client, config: Config, store: FeedStore, feed: Feed
) -> None:
    for attempt in store.pending_attempts(feed.name):
        try:
            message_id = reconcile_pending(client, config, attempt)
            if message_id is None:
                message_id = post_root_message(client, config, attempt.expected_body)
        except RejectedChattoError:
            store.discard_attempt(feed.name, attempt.guid)
            raise
        store.confirm(feed.name, attempt.guid, message_id)

    for episode in fetch_episodes(client, feed.url):
        if store.contains(feed.name, episode.guid):
            continue
        body = "\n\n".join(
            filter(None, (episode.title, episode.description, episode.link))
        )
        store.begin_attempt(feed.name, episode.guid, episode.link, body)
        try:
            message_id = post_root_message(client, config, body)
        except RejectedChattoError:
            store.discard_attempt(feed.name, episode.guid)
            raise
        store.confirm(feed.name, episode.guid, message_id)


def _finish_add(
    client: httpx.Client,
    config: Config,
    store: FeedStore,
    attempt: FeedPendingAttempt,
    *,
    reconcile_first: bool,
) -> str:
    try:
        message_id = (
            reconcile_pending(client, config, attempt) if reconcile_first else None
        )
        if message_id is None:
            message_id = post_root_message(client, config, attempt.expected_body)
    except RejectedChattoError:
        store.cancel_feed_add(attempt.feed_name, attempt.guid)
        raise
    store.complete_feed_add(attempt.feed_name, attempt.guid, message_id)
    return f"Added {attempt.feed_name}; proof post {message_id} confirmed"


def _validate_feed_input(name: str, url: str, interval_minutes: int) -> None:
    if not isinstance(name, str) or _FEED_NAME.fullmatch(name) is None:
        raise FeedError(
            "feed name must start with a letter or digit and use only letters, digits, _ or -"
        )
    if (
        not isinstance(interval_minutes, int)
        or isinstance(interval_minutes, bool)
        or interval_minutes < 10
        or interval_minutes > 9_223_372_036_854_775_807
    ):
        raise FeedError("feed interval must be an integer of at least 10 minutes")
    if not isinstance(url, str) or not url or url.strip() != url:
        raise FeedError("feed URL must be a valid HTTP(S) URL")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port != 0
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise FeedError("feed URL must be a valid HTTP(S) URL")
