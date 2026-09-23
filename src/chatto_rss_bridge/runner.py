from __future__ import annotations

import httpx

from .chatto import post_root_message
from .config import Config
from .rss import fetch_episode


def run_once(config: Config, *, http_client: httpx.Client | None = None) -> str:
    if http_client is None:
        with httpx.Client(timeout=15.0) as client:
            return _run_once(config, client)
    return _run_once(config, http_client)


def _run_once(config: Config, client: httpx.Client) -> str:
    episode = fetch_episode(client, config.rss_source)
    body = f"{episode.title}\n\n{episode.description}\n\n{episode.link}"
    message_id = post_root_message(client, config, body)
    return f"Posted {episode.title} ({message_id})"
