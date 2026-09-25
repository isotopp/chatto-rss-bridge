from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree

import httpx

MAX_FEED_BYTES = 5 * 1024 * 1024
FEED_REQUEST_TIMEOUT_SECONDS = 15.0


class FeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Episode:
    guid: str
    title: str
    published_at: datetime
    description: str
    link: str


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "div", "li", "p"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "li", "p"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(description: str) -> str:
    parser = _DescriptionParser()
    parser.feed(description)
    return " ".join("".join(parser.parts).split())


def fetch_episodes(client: httpx.Client, source: str) -> list[Episode]:
    try:
        with client.stream(
            "GET", source, timeout=FEED_REQUEST_TIMEOUT_SECONDS
        ) as response:
            if not response.is_success:
                raise FeedError(
                    f"RSS feed request returned HTTP {response.status_code}"
                )
            content = bytearray()
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > MAX_FEED_BYTES:
                    raise FeedError("RSS feed response is too large")
                content.extend(chunk)
    except httpx.HTTPError as exc:
        raise FeedError("RSS feed request failed") from exc

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise FeedError("RSS feed returned invalid XML") from exc
    if root.tag != "rss":
        raise FeedError("RSS feed root element is not rss")
    channel = root.find("channel")
    if channel is None:
        raise FeedError("RSS feed is missing channel")
    items = channel.findall("item")
    episodes = []
    for item in items:
        description = item.find("description")
        values = {
            "guid": item.findtext("guid"),
            "title": item.findtext("title"),
            "published_at": item.findtext("pubDate"),
            "description": "".join(description.itertext())
            if description is not None
            else None,
            "link": item.findtext("link"),
        }
        cleaned = {
            name: value.strip()
            for name, value in values.items()
            if isinstance(value, str) and value.strip()
        }
        missing = [name for name in values if name not in cleaned]
        if missing:
            raise FeedError(
                f"RSS item is missing required fields: {', '.join(missing)}"
            )

        try:
            published_at = parsedate_to_datetime(cleaned["published_at"])
        except ValueError as exc:
            raise FeedError("RSS item has an invalid publication date") from exc
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise FeedError("RSS item publication date must include a timezone")

        episodes.append(
            Episode(
                guid=cleaned["guid"],
                title=cleaned["title"],
                published_at=published_at,
                description=_plain_text(cleaned["description"]),
                link=cleaned["link"],
            )
        )
    return sorted(episodes, key=lambda episode: episode.published_at)
