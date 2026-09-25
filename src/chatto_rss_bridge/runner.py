from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .chatto import RejectedChattoError, post_root_message
from .config import Config
from .reconciliation import reconcile_pending
from .rss import fetch_episodes
from .state import SeenStore

_BERLIN = ZoneInfo("Europe/Berlin")


def run_once(
    config: Config,
    *,
    first_run: bool = False,
    clear_feed: bool = False,
    http_client: httpx.Client | None = None,
) -> str:
    if clear_feed:
        store = SeenStore(config.state_path)
        try:
            with store.locked():
                store.clear()
        finally:
            store.close()
        return "Cleared feed history"
    if http_client is None:
        with httpx.Client(timeout=15.0) as client:
            return _run_once(config, client, first_run=first_run)
    return _run_once(config, http_client, first_run=first_run)


def _run_once(config: Config, client: httpx.Client, *, first_run: bool = False) -> str:
    store = SeenStore(config.state_path)
    try:
        with store.locked():
            return _run_locked(config, client, store, first_run=first_run)
    finally:
        store.close()


def _run_locked(
    config: Config, client: httpx.Client, store: SeenStore, *, first_run: bool
) -> str:
    # ponytail: one lock per database; finer locks only if feeds share state.
    for attempt in store.pending_attempts():
        message_id = reconcile_pending(client, config, attempt)
        if message_id is None:
            try:
                message_id = post_root_message(client, config, attempt.expected_body)
            except RejectedChattoError:
                store.discard_attempt(attempt.guid)
                raise
        store.confirm(attempt.guid, message_id)

    episodes = fetch_episodes(client, config.rss_source)
    today = datetime.now(_BERLIN).date() if first_run else None
    posted: list[tuple[str, str]] = []
    for episode in episodes:
        if first_run and episode.published_at.astimezone(_BERLIN).date() != today:
            if not store.contains(episode.guid):
                store.skip(episode.guid)
            continue
        if store.contains(episode.guid):
            continue
        body = "\n\n".join(
            filter(None, (episode.title, episode.description, episode.link))
        )
        store.begin_attempt(episode.guid, episode.link, body)
        try:
            message_id = post_root_message(client, config, body)
        except RejectedChattoError:
            store.discard_attempt(episode.guid)
            raise
        store.confirm(episode.guid, message_id)
        posted.append((episode.title, message_id))

    if not episodes:
        return "No episodes to post"
    if not posted:
        return "No new episodes to post"
    if len(posted) == 1:
        return f"Posted {posted[0][0]} ({posted[0][1]})"
    return f"Posted {len(posted)} new episodes"
