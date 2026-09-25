from __future__ import annotations

from typing import Any

import httpx

from .config import Config


class ChattoError(RuntimeError):
    pass


class RejectedChattoError(ChattoError):
    pass


class UncertainChattoError(ChattoError):
    pass


class ReconciliationError(RuntimeError):
    pass


def _read_connect_json(
    client: httpx.Client, config: Config, method: str, payload: dict[str, object]
) -> dict[str, Any]:
    url = config.chatto_base_url + "/api/connect/chatto.api.v1." + method
    try:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise ReconciliationError("Chatto read request failed") from exc
    if not response.is_success:
        raise ReconciliationError(
            f"Chatto read request returned HTTP {response.status_code}"
        )
    try:
        result: Any = response.json()
    except ValueError as exc:
        raise ReconciliationError("Chatto returned an invalid read response") from exc
    if not isinstance(result, dict):
        raise ReconciliationError("Chatto returned an invalid read response")
    return result


def get_viewer_id(client: httpx.Client, config: Config) -> str:
    result = _read_connect_json(client, config, "ViewerService/GetViewer", {})
    user = result.get("user")
    profile = user.get("profile") if isinstance(user, dict) else None
    user_id = profile.get("id") if isinstance(profile, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise ReconciliationError("Chatto viewer response did not contain a user ID")
    return user_id


def search_messages(
    client: httpx.Client,
    config: Config,
    article_link: str,
    *,
    cursor: str | None = None,
) -> dict[str, Any]:
    query = f'"{article_link}"'
    payload: dict[str, object] = {
        "query": query,
        "roomId": config.room_id,
        "pageSize": 100,
    }
    if cursor is not None:
        payload["cursor"] = cursor
    return _read_connect_json(
        client, config, "MessageSearchService/SearchMessages", payload
    )


def get_room_events(
    client: httpx.Client,
    config: Config,
    *,
    before: str | None = None,
    after: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, object] = {"roomId": config.room_id, "limit": 500}
    if before is not None:
        payload["cursor"] = {"before": before}
    elif after is not None:
        payload["cursor"] = {"after": after}
    return _read_connect_json(client, config, "RoomService/GetRoomEvents", payload)


def post_root_message(client: httpx.Client, config: Config, body: str) -> str:
    return _post_message(
        client,
        config,
        {"roomId": config.room_id, "body": body},
    )


def post_reply_message(
    client: httpx.Client,
    config: Config,
    body: str,
    *,
    thread_root_event_id: str,
    in_reply_to: str,
) -> str:
    return _post_message(
        client,
        config,
        {
            "roomId": config.room_id,
            "body": body,
            "threadRootEventId": thread_root_event_id,
            "inReplyTo": in_reply_to,
        },
    )


def _post_message(client: httpx.Client, config: Config, payload: dict[str, str]) -> str:
    url = (
        config.chatto_base_url
        + "/api/connect/chatto.api.v1.MessageService/CreateMessage"
    )
    try:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise UncertainChattoError("Chatto message request failed") from exc
    if not response.is_success:
        error = f"Chatto returned HTTP {response.status_code}"
        error_type = (
            RejectedChattoError
            if 400 <= response.status_code < 500
            else UncertainChattoError
        )
        raise error_type(error)
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise UncertainChattoError(
            "Chatto returned invalid message confirmation"
        ) from exc
    message = payload.get("message") if isinstance(payload, dict) else None
    message_id = message.get("id") if isinstance(message, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise UncertainChattoError("Chatto response did not confirm a message ID")
    return message_id
