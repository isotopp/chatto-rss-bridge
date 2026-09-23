from __future__ import annotations

import httpx

from .chatto import post_root_message
from .config import Config
from .rss import fetch_episodes
from .state import SeenStore


def run_once(config: Config, *, http_client: httpx.Client | None = None) -> str:
    if http_client is None:
        with httpx.Client(timeout=15.0) as client:
            return _run_once(config, client)
    return _run_once(config, http_client)


def _run_once(config: Config, client: httpx.Client) -> str:
    store = SeenStore(config.state_path)
    try:
        episodes = fetch_episodes(client, config.rss_source)
        posted: list[tuple[str, str]] = []
        for episode in episodes:
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
