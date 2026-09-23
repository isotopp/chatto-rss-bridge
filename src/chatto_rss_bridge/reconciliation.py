from __future__ import annotations

from typing import Any

import httpx

from .chatto import (
    ReconciliationError,
    get_room_events,
    get_viewer_id,
    search_messages,
)
from .config import Config
from .state import PendingAttempt

_NON_MESSAGE_EVENTS = {
    "roomCreated",
    "roomUpdated",
    "roomDeleted",
    "roomArchived",
    "roomUnarchived",
    "roomThreadingModeChanged",
    "userJoinedRoom",
    "userLeftRoom",
    "callStarted",
    "callEnded",
}


def reconcile_pending(
    client: httpx.Client, config: Config, attempt: PendingAttempt
) -> str | None:
    viewer_id = get_viewer_id(client, config)
    try:
        message_id = _search_for_message(client, config, attempt, viewer_id)
    except ReconciliationError:
        message_id = None
    if message_id is not None:
        return message_id
    return _scan_timeline(client, config, attempt, viewer_id)


def _search_for_message(
    client: httpx.Client, config: Config, attempt: PendingAttempt, viewer_id: str
) -> str | None:
    cursor = None
    cursors: set[str] = set()
    while True:
        response = search_messages(client, config, attempt.article_link, cursor=cursor)
        results = response.get("results", [])
        if not isinstance(results, list):
            return None
        for result in results:
            if not isinstance(result, dict):
                continue
            message_id = _match_message(
                result.get("message"),
                room_id=config.room_id,
                viewer_id=viewer_id,
                expected_body=attempt.expected_body,
            )
            if message_id is not None:
                return message_id

        next_cursor = response.get("nextCursor")
        if next_cursor in (None, ""):
            return None
        if not isinstance(next_cursor, str) or next_cursor in cursors:
            return None
        cursors.add(next_cursor)
        cursor = next_cursor


def _scan_timeline(
    client: httpx.Client, config: Config, attempt: PendingAttempt, viewer_id: str
) -> str | None:
    initial = _timeline_page(get_room_events(client, config))
    message_id = _page_match(
        initial,
        room_id=config.room_id,
        viewer_id=viewer_id,
        expected_body=attempt.expected_body,
    )
    if message_id is not None:
        return message_id

    for direction, has_key, cursor_key in (
        ("before", "hasOlder", "startCursor"),
        ("after", "hasNewer", "endCursor"),
    ):
        page = initial
        cursors: set[str] = set()
        while _has_more(page, has_key):
            cursor = page.get(cursor_key)
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ReconciliationError(
                    "Chatto returned incomplete timeline pagination"
                )
            cursors.add(cursor)
            response = get_room_events(
                client,
                config,
                before=cursor if direction == "before" else None,
                after=cursor if direction == "after" else None,
            )
            page = _timeline_page(response)
            message_id = _page_match(
                page,
                room_id=config.room_id,
                viewer_id=viewer_id,
                expected_body=attempt.expected_body,
            )
            if message_id is not None:
                return message_id
    return None


def _timeline_page(response: dict[str, Any]) -> dict[str, Any]:
    page = response.get("page")
    if not isinstance(page, dict) or not isinstance(page.get("events", []), list):
        raise ReconciliationError("Chatto returned an incomplete room timeline")
    for key in ("hasOlder", "hasNewer"):
        if key in page and not isinstance(page[key], bool):
            raise ReconciliationError("Chatto returned an incomplete room timeline")
    return page


def _has_more(page: dict[str, Any], key: str) -> bool:
    value = page.get(key, False)
    if not isinstance(value, bool):
        raise ReconciliationError("Chatto returned an incomplete room timeline")
    return value


def _page_match(
    page: dict[str, Any], *, room_id: str, viewer_id: str, expected_body: str
) -> str | None:
    for event in page.get("events", []):
        if not isinstance(event, dict):
            raise ReconciliationError("Chatto returned an incomplete room timeline")
        variants = {
            key: value
            for key, value in event.items()
            if key not in {"id", "createdAt", "actorId"}
        }
        if len(variants) != 1:
            raise ReconciliationError("Chatto returned an incomplete room timeline")
        variant, payload = next(iter(variants.items()))
        if variant != "messagePosted":
            if variant in _NON_MESSAGE_EVENTS:
                continue
            raise ReconciliationError("Chatto returned an unsupported timeline event")
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            raise ReconciliationError("Chatto returned an incomplete room timeline")
        if (
            not all(
                isinstance(message.get(field), str)
                for field in ("id", "roomId", "actorId", "body")
            )
            or not message["id"]
            or not message["roomId"]
            or not message["actorId"]
        ):
            raise ReconciliationError("Chatto returned an incomplete room timeline")
        if message["roomId"] != room_id:
            raise ReconciliationError("Chatto returned a message from the wrong room")
        if event.get("actorId") != message["actorId"]:
            raise ReconciliationError("Chatto returned inconsistent message authorship")
        message_id = _match_message(
            message,
            room_id=room_id,
            viewer_id=viewer_id,
            expected_body=expected_body,
        )
        if message_id is not None:
            return message_id
    return None


def _match_message(
    message: Any,
    *,
    room_id: str,
    viewer_id: str,
    expected_body: str,
) -> str | None:
    if not isinstance(message, dict):
        return None
    message_id = message.get("id")
    if (
        isinstance(message_id, str)
        and message_id
        and message.get("roomId") == room_id
        and message.get("actorId") == viewer_id
        and message.get("body") == expected_body
    ):
        return message_id
    return None
