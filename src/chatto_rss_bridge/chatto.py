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


def post_root_message(client: httpx.Client, config: Config, body: str) -> str:
    url = (
        config.chatto_base_url
        + "/api/connect/chatto.api.v1.MessageService/CreateMessage"
    )
    try:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={"roomId": config.room_id, "body": body},
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
