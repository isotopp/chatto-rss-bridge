from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

import httpx


class FeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Episode:
    guid: str
    title: str
    published_at: str
    description: str
    link: str


def fetch_episode(client: httpx.Client, source: str) -> Episode:
    try:
        response = client.get(source)
    except httpx.HTTPError as exc:
        raise FeedError("RSS feed request failed") from exc
    if not response.is_success:
        raise FeedError(f"RSS feed request returned HTTP {response.status_code}")

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise FeedError("RSS feed returned invalid XML") from exc
    if root.tag != "rss":
        raise FeedError("RSS feed root element is not rss")
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    if len(items) != 1:
        raise FeedError("expected one RSS item")

    item = items[0]
    values = {
        "guid": item.findtext("guid"),
        "title": item.findtext("title"),
        "published_at": item.findtext("pubDate"),
        "description": item.findtext("description"),
        "link": item.findtext("link"),
    }
    cleaned = {
        name: value.strip()
        for name, value in values.items()
        if isinstance(value, str) and value.strip()
    }
    missing = [name for name in values if name not in cleaned]
    if missing:
        raise FeedError(f"RSS item is missing required fields: {', '.join(missing)}")
    return Episode(
        guid=cleaned["guid"],
        title=cleaned["title"],
        published_at=cleaned["published_at"],
        description=cleaned["description"],
        link=cleaned["link"],
    )
