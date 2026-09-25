# Room-managed RSS feeds: ticket plan

This plan implements the approved [user stories](user-stories.md) in order.
Each code ticket starts with a failing behavior test and ends with the project
checks.

## 1. Verify the deployed mention and reply contract

Behavior and public interface:

- Establish, using the deployed Chatto version or its matching API schema,
  how a bot receives direct-mention events, obtains the mentioned message and
  sender ID, and posts a reply in the command's thread.
- Record the verified request and response shapes as controlled test fixtures
  before later tickets depend on them.

Completed in [integration-contract.md](integration-contract.md), with
synthetic controlled fixtures in `tests/fixtures/chatto_direct_mention.json`
and `tests/fixtures/chatto_thread_reply.json`. The deployed server reports
`0.5.0-beta.6` and accepted an authenticated, read-only realtime subscription.
Role lookup is already verified: the deployed bot API key can call
`UserService/GetUser` and read `user.roles` without an admin permission.

## 2. Persist named feeds and feed-scoped delivery state

Behavior and public interface:

- The state layer can add, list, find, and delete a named feed with URL and
  interval. A duplicate name is rejected; an unknown name is reported.
- Seen GUIDs and pending posts belong to a feed. Identical GUIDs in two feeds
  do not collide, and all state survives reopening the database.
- No configured feed is imported from `BOT_RSS_SOURCE`; the operator adds it
  through Chatto after deployment.

Done when the state layer's behavior is covered without network access.

Completed: `FeedStore` persists named feed definitions and per-feed seen and
pending records. Tests cover reopen persistence, overlapping GUIDs, duplicate
and unknown feed errors, deletion and re-add, pending-delete protection, and
the absence of legacy history import.

## 3. Add a feed with one proof post

Behavior and public interface:

- `add <feedname> <url> <minutes>` rejects malformed names or URLs, intervals
  below 10 minutes, duplicate names, invalid feeds, and empty feeds without
  activating a feed. Names are 1 to 64 ASCII letters, digits, `_`, or `-`,
  starting with a letter or digit.
- A valid add posts the newest item by publication time, confirms or
  reconciles that post, marks every item in the initial snapshot seen, and
  activates the feed at the requested interval.
- A lost post response cannot cause a duplicate proof post. A repeated
  command cannot create another feed or proof post.

Done when controlled Chatto and RSS responses exercise confirmed, rejected,
and uncertain proof delivery.

Completed: `feed_service.add_feed` validates feed input, fetches at most a
5 MiB RSS document with a 15 second timeout, posts the newest item, and only
activates the feed after confirmation. Pending proof posts preserve the
initial GUID snapshot and are reconciled before any retry.

## 4. Poll active feeds independently

Behavior and public interface:

- A feed check posts only unseen items, oldest first, and retains the current
  uncertain-delivery reconciliation behavior for each feed.
- A failed feed check leaves its feed and history intact and does not stop
  other feeds from being checked.
- Each feed becomes due according to its own configured interval, including
  after a process restart.

Done when checks of two feeds with overlapping GUIDs and different intervals
show independent results.

## 5. Parse and answer room commands

Behavior and public interface:

- A directly mentioned bot recognizes `add`, `list`, `delete`, and `help` with
  exact argument counts. It ignores unrelated, edited, and bot-authored
  messages and messages outside `BOT_ROOM_ID`.
- `list` returns names, URLs, and intervals; `delete` stops a known feed;
  `help` gives usage guidance to any room member. All outcomes reply in the
  command thread without leaking credentials.
- A duplicate mention event cannot execute a state-changing command again.

Done when the command handler is testable with message and API fixtures, with
no live Chatto connection.

## 6. Authorize feed commands

Behavior and public interface:

- `add`, `list`, and `delete` require the sender's current membership in the
  role named by `BOT_BRIDGE_ROLE`.
- The handler calls `UserService/GetUser` with the message sender's stable
  user ID and requires an exact role-name match in `user.roles`.
- Missing users or roles, malformed responses, and failed lookups deny the
  command. `help` remains available to room members.

Done when allowed, denied, and lookup-error cases pass using controlled API
responses.

## 7. Run a reconnecting listener and feed scheduler

Behavior and public interface:

- One service process handles Chatto mention events and due feed checks.
- It reconnects after a transient disconnect, resumes from the safest
  available cursor, and persists enough command identity to ignore replays.
- A long gap that cannot be replayed is reported and does not cause old
  commands to be guessed or applied.
- Graceful shutdown closes resources; systemd can restart the process.

Done when a controlled disconnect/replay and a restart preserve feed checks
and avoid repeated commands.

## 8. Document and package operation

Behavior and public interface:

- `sample.env` and `README.md` describe `BOT_BRIDGE_ROLE`, room commands,
  manual Presseschau add, and a restartable systemd service without a timer.
- Old one-shot flags and `BOT_RSS_SOURCE` are removed from the documented
  operator path when the long-running service replaces them.
- The documented setup requires only the permissions confirmed in ticket 1.

Done when an operator can install, start, and inspect the service from the
README without guessing its configuration or handling secrets in logs.

## Re-add policy

Deleting a feed removes its active definition and confirmed history after any
pending post has been reconciled. Re-adding the same name is a new add: it
posts the current newest article as the proof post and marks the current feed
snapshot seen. `delete` refuses while a post for that feed remains uncertain.
