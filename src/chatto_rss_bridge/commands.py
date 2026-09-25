from __future__ import annotations

import shlex
from typing import Any

import httpx

from .chatto import (
    AuthorizationError,
    ChattoError,
    ReconciliationError,
    get_user_roles,
    post_reply_message,
)
from .config import Config
from .feed_service import add_feed
from .rss import FeedError
from .state import FeedNotFoundError, FeedStore, StateError

_HELP = "Commands: add <feedname> <url> <minutes>; list; delete <feedname>; help"


def handle_message(
    client: httpx.Client,
    config: Config,
    store: FeedStore,
    *,
    bot_user_id: str,
    event: dict[str, Any],
) -> bool:
    command = _command_from_event(event, config.room_id, bot_user_id)
    if command is None:
        return False

    event_id, actor_id, message, name, args = command
    if not store.claim_command(event_id):
        return True
    if name in {"add", "list", "delete"}:
        try:
            roles = get_user_roles(client, config, actor_id)
        except AuthorizationError:
            reply_body = "Could not verify your role; command denied."
        else:
            if config.bot_bridge_role not in roles:
                reply_body = f"This command requires the {config.bot_bridge_role} role."
            else:
                reply_body = _execute(client, config, store, name, args)
    else:
        reply_body = _execute(client, config, store, name, args)
    thread_root = message.get("threadRootEventId")
    if not isinstance(thread_root, str) or not thread_root:
        thread_root = event_id
    post_reply_message(
        client,
        config,
        reply_body,
        thread_root_event_id=thread_root,
        in_reply_to=event_id,
    )
    return True


def _command_from_event(
    event: dict[str, Any], room_id: str, bot_user_id: str
) -> tuple[str, str, dict[str, Any], str, list[str]] | None:
    message = event.get("messagePosted")
    if (
        not isinstance(message, dict)
        or message.get("roomId") != room_id
        or message.get("echoOfEventId")
    ):
        return None

    event_id = event.get("id")
    actor_id = event.get("actorId")
    body = message.get("bodyPlaintext")
    mentions = message.get("mentions")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(actor_id, str)
        or not actor_id
        or actor_id == bot_user_id
        or not isinstance(body, str)
        or not isinstance(mentions, list)
    ):
        return None
    if not any(
        isinstance(mention, dict)
        and mention.get("includesViewer") is True
        and isinstance(mention.get("direct"), dict)
        and mention["direct"].get("userId") == bot_user_id
        for mention in mentions
    ):
        return None

    try:
        parts = shlex.split(body)
    except ValueError:
        parts = []
    if parts and parts[0].startswith("@"):
        parts = parts[1:]
    if not parts:
        return event_id, actor_id, message, "", []
    return event_id, actor_id, message, parts[0].casefold(), parts[1:]


def _execute(
    client: httpx.Client,
    config: Config,
    store: FeedStore,
    name: str,
    args: list[str],
) -> str:
    if name == "help":
        return _HELP if not args else f"Usage: help\n{_HELP}"
    if name == "list":
        if args:
            return "Usage: list"
        try:
            feeds = store.list_feeds()
        except StateError as exc:
            return f"Could not list feeds: {exc}"
        if not feeds:
            return "No feeds configured."
        return "\n".join(
            f"{feed.name} — {feed.url} — every {feed.interval_minutes} minutes"
            for feed in feeds
        )
    if name == "add":
        if len(args) != 3:
            return "Usage: add <feedname> <url> <minutes>"
        try:
            interval = int(args[2])
            return add_feed(
                client,
                config,
                store,
                name=args[0],
                url=args[1],
                interval_minutes=interval,
            )
        except (
            ValueError,
            ChattoError,
            FeedError,
            ReconciliationError,
            StateError,
        ) as exc:
            return f"Could not add feed: {exc}"
    if name == "delete":
        if len(args) != 1:
            return "Usage: delete <feedname>"
        try:
            store.delete_feed(args[0])
        except FeedNotFoundError:
            return f"No feed named {args[0]}."
        except StateError:
            return f"Cannot delete {args[0]} while one of its posts is uncertain."
        return f"Deleted feed {args[0]}."
    return f"Unknown command. {_HELP}"
