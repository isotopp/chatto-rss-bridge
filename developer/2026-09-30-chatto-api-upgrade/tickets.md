# Chatto 0.5-beta.10 API upgrade: ticket plan

This plan covers [US-1](user-stories.md) in implementation order. Status:
approved for implementation by the user on 2026-09-30; plan committed in `f684b10`.
The user story is already committed in `dea396a`.

Each code change starts with a failing behavior test using controlled
responses. Reuse existing coverage where the contract already matches. Each
code ticket ends with `uv run ruff check --fix`, `uv run ruff format`,
`uv run ty check`, and `uv run pytest`, then a ticket commit.

## Planning evidence

On 2026-09-30, the updated local Chatto checkout and the
[published release](https://github.com/chattocorp/chatto/releases/tag/v0.5.0-beta.10)
confirmed the target as `v0.5.0-beta.10`, commit
`ef35cd000259c243f3c377227bd6007d5b750647`.

Comparing that tag with `v0.5.0-beta.6` found unchanged schemas for the viewer
snapshot, user lookup response and directory roles, message creation, message
search, room timelines, and realtime messages consumed by the bridge. Added
user profile update methods are outside this bridge's scope. Realtime remains
protocol version 4.

The current bridge nevertheless sends room timeline pagination as
`{"cursor": {"before": "..."}}` or its `after` equivalent. The target's
`proto/chatto/api/v1/room_timeline.proto` declares a protobuf oneof whose JSON
fields are top-level `before` and `after`. Ticket 2 corrects this existing
contract mismatch. No live target-server probe has been performed for this
plan; source verification must be distinguished from deployment verification.

## 1. Record the target integration contract

Behavior and public interface:

- Record the exact target tag and commit in this epic's
  `integration-contract.md`, with upstream source references for bot bearer
  authentication, viewer identity, role lookup, root posts and thread replies,
  message search, room timelines, and realtime subscription and recovery.
- Identify the request and response shapes used by the bridge, including
  `user.profile.id`, directory `user.roles`, message confirmations, top-level
  timeline pagination, and realtime protocol version 4 and field numbers.
- Compare the bridge's requests and consumed fields with the target release;
  record which interfaces already match and every necessary correction.
- Verify permissions through the matching server handlers and tests. Record
  source evidence separately from any read-only deployed-server observations.
  Do not post to a live room or expose credentials.

Done when the contract supports the remaining tickets without guessed API
details. If verification reveals additional required behavior changes, update
this plan and obtain approval before implementing them.

Completed: [integration-contract.md](integration-contract.md) records the
release schemas, authentication and permission evidence, the pagination
correction, and the remaining deployment acceptance checks. Source verification
requires no additional API changes beyond the approved plan.

## 2. Reconcile uncertain posts using valid timeline pagination

Depends on ticket 1.

Behavior and public interface:

- `get_room_events` sends `roomId` and `limit` for an initial page, top-level
  `before` for an older page, or top-level `after` for a newer page, as required
  by `RoomService/GetRoomEvents` in the verified contract.
- When search is unavailable or finds no matching message, reconciliation
  follows the returned timeline cursors in both directions and recognizes a
  matching bot post beyond the initial page without sending it again.
- Only a matching room, bot author, and exact expected body confirm delivery.
  A complete negative timeline read permits a retry; failed reads, malformed
  pages, missing continuation cursors, and cursor cycles remain inconclusive
  and preserve the pending attempt.

Done when controlled HTTP responses reject the old nested cursor shape and
exercise successful reconciliation on subsequent older and newer pages, plus
inconclusive reads that must not trigger a duplicate post.

Completed: `get_room_events` sends top-level `before` and `after`. The existing
negative-read regression now enforces the target request shape. Feed polling
tests find pending deliveries on older and newer pages after reopening the
database, with empty or unavailable search, and retain pending state for
failed, malformed, incomplete, and cyclic timeline reads. Both pagination
regressions failed before their fixes. Required checks pass: 82 tests.

## 3. Verify command, delivery, and realtime compatibility

Depends on tickets 1 and 2.

Behavior and public interface:

- The configured bot authenticates and obtains its stable viewer ID from the
  target viewer response. Management commands check the sender's current
  directory roles on every command, requiring an exact `BOT_BRIDGE_ROLE`
  match; missing or malformed roles and failed lookups deny access.
- Target-format binary direct mentions in the configured room reach the
  command handler. Other rooms, edits, self-authored messages, echoes, and
  indirect mentions do not trigger commands; replies use the source message's
  thread root and reply attribution.
- `add`, `list`, `delete`, and `help` retain their documented behavior. Proof
  posts and subsequent RSS articles are root messages; rejected or uncertain
  responses cannot become confirmed delivery without valid evidence.
- After a disconnect or restart, saved feeds, delivery history, pending
  attempts, and command identities remain effective. Replayed commands do
  not run again; expired resume cursors report the gap and recover at the live
  boundary without guessing missed commands.
- Existing JSON and binary fixtures are checked against the target contract.
  Change bridge code or the protobuf subset only where verified incompatibility
  requires it.

Done when existing coverage and any necessary focused additions demonstrate
these behaviors with controlled HTTP, WebSocket, RSS, and persistent-state
inputs. Tests require no network access, live posts, or live service setup.

## 4. Document the supported release and upgrade operation

Depends on tickets 1 through 3.

Behavior and public interface:

- `README.md` identifies Chatto `0.5.0-beta.10` as the verified target and links
  to this epic's integration contract.
- Bot creation, permissions, configuration, service operation, and recovery
  instructions match the verified release. Any required operator changes are
  explicit, including the effect on persisted state or old resume cursors if
  verification establishes such a change.
- An operator can upgrade and restart the bridge while retaining saved feeds
  and delivery history. Document any deployment-only acceptance checks and
  distinguish them from offline verification.

Done when the README and contract agree with the completed tickets and the
required project checks pass. Deployment acceptance that posts to Chatto is
performed separately with explicit authorization.
