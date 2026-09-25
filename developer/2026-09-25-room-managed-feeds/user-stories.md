# Room-managed RSS feeds

## Goal and agreed behavior

Replace the hourly one-shot timer with a long-running systemd service. The bot
listens for direct mentions in its configured Chatto room and polls a persistent
set of RSS feeds. A trusted user can manage feeds through room commands. The
existing Presseschau feed is added manually; there is no migration from
`BOT_RSS_SOURCE`.

Commands are `@bot add <feedname> <url> <minutes>`, `@bot list`,
`@bot delete <feedname>`, and `@bot help`. A polling interval is an integer
number of minutes, at least 10. `help` is available to room members; the other
commands require authorization. The bot replies to a command in its thread.

On `add`, the bot fetches and validates the feed, posts its most recent article
to prove that the feed works, marks every article in that initial snapshot as
seen, and subsequently posts only new articles. Each feed has its own polling
interval and delivery history.

Management commands require current membership in the Chatto role named by
`BOT_BRIDGE_ROLE`. The bot checks the message sender's stable user ID through
`UserService/GetUser` and reads the returned `user.roles`. This read was
verified with the deployed bot API key without admin permission.

## US-1: Listen for room commands

As a room member, I want the bot to respond to a direct mention so that I can
control it without server access.

Acceptance criteria:

- The service processes direct mentions of this bot in the configured room,
  including messages in threads; it ignores other rooms, unrelated messages,
  edits, and its own messages.
- It recognizes only the documented commands and exact argument counts, and
  replies in the command's thread with the outcome or usage guidance.
- `help` explains available commands and their arguments without exposing
  credentials or private configuration.
- A reconnect or duplicate event cannot execute the same command twice.
- A delayed or missed event cannot make an unauthorized command effective.

## US-2: Authorize management commands

As an operator, I want only designated people to change or inspect the feed
set so that room membership alone does not grant control.

Acceptance criteria:

- `add`, `list`, and `delete` require the sender's current membership in the
  role named by `BOT_BRIDGE_ROLE`.
- The bot calls `UserService/GetUser` with the sender's stable Chatto user ID
  and requires an exact match in the returned `user.roles`; message text and
  usernames do not establish authorization.
- A missing role, missing user, malformed response, or failed lookup denies
  the command. Role assignment and revocation take effect on the next check.

## US-3: Add a feed with an initial proof post

As a trusted user, I want to add a named RSS feed and immediately see its
latest article so that I know the feed and posting permissions work.

Acceptance criteria:

- `add` accepts a unique feed name, an HTTP(S) feed URL, and an integer polling
  interval of at least 10 minutes. Invalid input or an invalid or empty feed
  does not activate a feed.
- The bot fetches a bounded response with a timeout, parses it using the
  existing RSS rules, and selects the latest article by publication time.
- It posts that article to the configured room, marks all articles in the
  initial snapshot as seen, and persists the feed with its polling interval.
- If posting is rejected, the feed does not become active. If delivery is
  uncertain, the bridge retains enough state to reconcile before retrying or
  activating the feed; it does not knowingly duplicate the proof post.
- An accidental repeated command or an existing feed name cannot create a
  second feed or proof post.

## US-4: Poll every saved feed

As a reader, I want new articles from each configured feed to appear in the
room without manual commands.

Acceptance criteria:

- The service checks each active feed at its own interval and posts unseen
  articles in publication order, oldest first.
- Seen and pending delivery records are scoped to a feed, so two feeds with
  the same RSS GUID remain independent.
- The existing uncertain-post reconciliation and no-duplicate safeguards
  apply to every feed and survive a service restart.
- One feed's fetch or parse failure is reported to the operator and does not
  stop checks of other feeds. The failed feed retains its history and is
  retried on a later interval.

## US-5: List and delete feeds

As a trusted user, I want to inspect and remove configured feeds so that the
service follows the intended sources.

Acceptance criteria:

- `list` reports each saved feed's name, URL, and polling interval.
- `delete <feedname>` stops future checks of that feed and confirms the
  result. An unknown name produces a useful error.
- `delete` refuses while a post for that feed remains uncertain. Otherwise it
  removes the feed definition and confirmed history. Re-adding the name makes
  a new proof post. Deleting one feed never affects another feed.

## US-6: Run as an unattended service

As an operator, I want one restartable service with durable state so that
commands and scheduled checks continue across disconnects and restarts.

Acceptance criteria:

- The service reconnects after a transient Chatto disconnect and resumes
  from the safest available event position. It never assumes an old event
  stream provides indefinite replay.
- Command deduplication, feed definitions, and delivery state survive process
  restarts.
- systemd restarts a failed process; no timer unit is required for feed
  checks. Shutdown closes network and database resources cleanly.
- Operator documentation explains bot permissions, configuration, commands,
  polling, failure recovery, and the manual addition of the Presseschau feed.
- Automated tests use controlled Chatto and RSS responses and never post to a
  live room or start a live service.

## Integration contract

The deployed version, authenticated realtime subscription, direct-mention
event schema, and thread reply request/response are recorded in
[integration-contract.md](integration-contract.md).
