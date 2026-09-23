from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .chatto import post_root_message
from .config import Config
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
            body = f"{episode.title}\n\n{episode.description}\n\n{episode.link}"
            message_id = post_root_message(client, config, body)
            store.confirm(episode.guid, message_id)
            posted.append((episode.title, message_id))
    finally:
        store.close()

    if not episodes:
        return "No episodes to post"
    if not posted:
        return "No new episodes to post"
    if len(posted) == 1:
        return f"Posted {posted[0][0]} ({posted[0][1]})"
    return f"Posted {len(posted)} new episodes"
