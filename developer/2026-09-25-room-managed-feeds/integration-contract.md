# Chatto mention and reply contract

Verified on 2026-09-25 against the configured Chatto server. Public
`ServerDiscoveryService/GetServer` reported `0.5.0-beta.6`, matching the
`v0.5.0-beta.6` tag in `~/Source/chatto`. The configured bot key received
HTTP 200 from `ViewerService/GetViewer` and `RoomService/GetRoomEvents` for
the configured room. A read-only `GET /api/realtime` WebSocket connection
upgraded with HTTP 101; a binary `RealtimeSubscribe` with protocol version 4,
the bot bearer token, and `LIVE_ONLY` received a binary `caught_up` frame.
No message was sent to the room.

## Incoming command

The WebSocket transports protobuf, not JSON. Send `RealtimeSubscribe` as the
first binary frame. In `RealtimeServerFrame.event`, inspect
`RealtimeEvent.message_posted`. The event's `id` is the message ID and
`actor_id` is the sender's stable user ID. `message_posted` supplies
`room_id`, `body_plaintext`, `thread_root_event_id`, `in_reply_to`,
`echo_of_event_id`, and `mentions`.

A direct mention of this bot is a `MessageMention` with `direct.user_id` equal
to the bot's viewer user ID and `includes_viewer = true`. Role, `here`, and
`all` mentions are different targets and must not trigger a command. Filter
to the configured room, skip the bot's own messages and channel echoes, and
deduplicate by event ID. A missing `body_plaintext` is not a command. The
synthetic decoded event in `tests/fixtures/chatto_direct_mention.json` records
the expected shape; it is not a captured live message. The listener keeps a
wire-compatible protobuf subset in `src/chatto_rss_bridge/realtime.proto`;
`tests/fixtures/chatto_realtime_mention.hex` is a synthetic binary frame that
checks its field numbers and decoding without a live Chatto connection.

## Reply

Call `POST /api/connect/chatto.api.v1.MessageService/CreateMessage` with a
JSON `CreateMessageRequest`. Set `roomId` to the incoming room, `body` to the
response, `threadRootEventId` to the incoming `threadRootEventId` if present
or otherwise to the incoming event `id`, and `inReplyTo` to that incoming
event `id`. Leave `alsoSendToChannel` false. The response contains `message`
with the generated `id`, `threadRootEventId`, and `inReplyTo`. The synthetic
request/response in `tests/fixtures/chatto_thread_reply.json` records this
shape; no live reply was posted.

Chatto requires room membership and thread reply permission (`message.post`,
`message.post-in-thread`, or an eligible interaction permission), plus read
access to the thread. The room's threading mode must permit replies. The bot
also needs `message.post` for root article posts.

The exact event and reply fields are from the matching tag's
`proto/chatto/realtime/v1/{realtime,events}.proto` and
`proto/chatto/api/v1/messages.proto`. The server's message projection is in
`cli/internal/http_server/realtime.go` and
`cli/internal/http_server/realtime_event_projection.go`; reply validation is
in `cli/internal/core/message_model.go`. The live probe verified the deployed
version and transport, while the matching release schema supplies the event
and write shapes. A live mention/reply round trip remains for deployment
acceptance because it would post to the room.
