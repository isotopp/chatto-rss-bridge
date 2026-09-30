# Chatto 0.5.0-beta.10 integration contract

Verified from the local Chatto checkout on 2026-09-30 at release tag
[`v0.5.0-beta.10`](https://github.com/chattocorp/chatto/releases/tag/v0.5.0-beta.10),
commit `ef35cd000259c243f3c377227bd6007d5b750647`. This is source verification,
not a probe of the deployed server. No live messages were posted.

Comparing the matching schemas with `v0.5.0-beta.6` showed no changes to the
fields used by the bridge. User profile update methods added to `UserService`
are outside its scope. The required correction is an existing bridge mismatch:
room timeline pagination must send top-level `before` or `after`, rather than
a nested `cursor` object. No state migration or realtime schema change is
required by the verified contract.

## HTTP authentication and identity

Requests use `POST /api/connect/chatto.api.v1.<Service>/<Method>` with JSON and
`Authorization: Bearer <bot API key>`. The base URL is the bare server origin.

- `ViewerService/GetViewer`, request `{}`: read the bot ID at
  `user.profile.id`.
- `UserService/GetUser`, request `{"userId": "<sender ID>"}`: the response's
  `user` is a `DirectoryMember`, with a public profile under `user.user` and
  current role names under `user.roles`. Require an exact `BOT_BRIDGE_ROLE`
  match for every management command. Missing roles mean no authorized role;
  missing users, malformed role lists, or failed reads deny the command.

Evidence: [viewer.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/viewer.proto),
[user_service.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/user_service.proto),
[member_directory.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/member_directory.proto).
The handler in [member_directory.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/connectapi/member_directory.go)
requires an authenticated caller for `GetUser`, with no admin permission gate.
[connect_test.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/http_server/connect_test.go)
contains `TestConnectBotAPIKeyAuthenticatesPublicAPIRequests`, which verifies
bot bearer authentication and the viewer profile shape.

## Root posts and command replies

Call `MessageService/CreateMessage` with `roomId` and `body` for an RSS root
post. For a command reply, also send `threadRootEventId` (the incoming root,
or the incoming event ID for a root command) and `inReplyTo` (the command event
ID). Omit `alsoSendToChannel`, whose default is false. A response confirms
delivery only when `message.id` is a nonempty string.

The bot needs room membership and effective `message.post` for root messages.
Thread replies require read access and `message.post`, `message.post-in-thread`,
or an eligible `message.post-in-interactions` relationship. The room's threading
mode must permit the placement. Keep broad `message.read` for full room
reconciliation; interaction-only access cannot establish complete absence.
The owner's permissions cap the bot's effective permissions.

Evidence: [messages.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/messages.proto),
[messages.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/connectapi/messages.go),
[bots_test.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/core/bots_test.go).
`tests/fixtures/chatto_thread_reply.json` is a synthetic matching example.

## Search and timeline reconciliation

`MessageSearchService/SearchMessages` accepts `query` (the quoted article
link), `roomId`, `pageSize` (maximum 100), and an optional top-level `cursor`.
Read `results[].message` and follow `nextCursor`. Results are current renderable
messages, with `id`, `roomId`, `actorId`, and optional `body`. A matching bot
author, room, and exact expected body establish delivery. Search absence alone
does not establish that an uncertain post was never delivered. Disabled search
returns `FAILED_PRECONDITION`; an unavailable provider returns `UNAVAILABLE`.

`RoomService/GetRoomEvents` accepts `roomId`, `limit` (maximum 500), and at most
one top-level `before` or `after`. Protobuf oneof names do not introduce a JSON
wrapper. Initial requests omit both fields. Subsequent requests use opaque
`page.startCursor` with `before` or `page.endCursor` with `after`, continuing
while `page.hasOlder` or `page.hasNewer` is true.

The response is `page.events[]`, each with `id`, `createdAt`, `actorId`, and
one event variant. `messagePosted.message` holds the renderable message.
Other supported timeline variants are room lifecycle and threading changes,
membership changes, and call start/end events. Malformed or incomplete reads
remain inconclusive and retain the pending post.

Evidence: [message_search.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/message_search.proto),
[room_timeline.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/room_timeline.proto),
[message_types.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/api/v1/message_types.proto),
[room_timeline.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/connectapi/room_timeline.go).

## Realtime commands and recovery

Open `GET /api/realtime` as a WebSocket. The first application message is a
binary protobuf `RealtimeSubscribe`: protocol version 4 (field 1), bot bearer
token (2), optional saved resume cursor (3), and `LIVE_ONLY` initial state (4).
The server sends protobuf frames, not JSON.

The bridge's wire subset matches the target: server `event`, `heartbeat`,
`close`, and `caught_up` variants are fields 1 through 4; event `id`, `actor_id`,
and `cursor` are 1, 3, and 4; `message_posted` is 24. Its room ID, reply ID,
thread root, echo ID, mentions, and optional plaintext are fields 1, 2, 3, 5,
7, and 8. Direct mention target field 2 contains `user_id` field 1;
`includes_viewer` is field 6. The added room-kind field can remain outside the
subset because the bridge filters by its configured room ID.

Only direct mentions of this bot with `includes_viewer = true` trigger commands.
Persist cursors after preceding frames have been processed. Cursors expire
15 minutes after issue. A `caught_up` recovery other than `RESUMED` after a
saved cursor reports a gap. `RESYNC_REQUIRED` clears the cursor before a
reconnect at the live boundary. Honor reconnect guidance and retry delay;
never infer commands missed during a gap. Command identities survive replays
and restarts independently of the cursor.

Evidence: [realtime.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/realtime/v1/realtime.proto),
[events.proto](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/proto/chatto/realtime/v1/events.proto),
[realtime.go](https://github.com/chattocorp/chatto/blob/v0.5.0-beta.10/cli/internal/http_server/realtime.go).
The JSON direct-mention and binary mention fixtures in `tests/fixtures/` are
synthetic examples checked against these field numbers, not live captures.

## Deployment acceptance

Offline tests cover requests, controlled responses, binary decoding, recovery,
and state persistence. Deployment acceptance still needs a server version
check and read-only authentication/subscription checks against the configured
server. A real mention/reply and RSS post require separately authorized live
messages and are not part of automated tests.
