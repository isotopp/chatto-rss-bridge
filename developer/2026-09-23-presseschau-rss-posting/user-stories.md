# Presseschau RSS posting

## Goal and agreed behavior

A scheduled, one-shot command publishes new episodes from the configured Deutschlandfunk Presseschau RSS feed to a configured Chatto room. The operator expects roughly four episodes per day and plans to run the command hourly with a systemd timer. Each episode becomes one root-level Chatto message; readers may start threads beneath it.

The command uses a persistent SQLite database to track feed GUIDs and posting attempts. A normal run with no previous state posts all items currently in the feed, oldest first. `--first-run` posts only items whose publication date is today and marks the entire current feed as seen. `--clear-feed` resets seen state so the next normal run can replay the feed.

We expect the SQLite database to be named `.chatto-rss-bridge.db` and be located next to the env file found: Either in the current directory, or in the user's home.

## Terms

- **Episode:** one RSS `<item>`, identified by its `<guid>`.
- **Today:** the calendar day of the episode's `<pubDate>` in the `Europe/Berlin` time zone, compared with the current day in that zone.
- **Confirmed post:** Chatto's `CreateMessage` response includes a message ID.
- **Uncertain post:** a request may have reached Chatto, but the command did not receive a valid confirmation.

## US-1: Load and validate operator configuration

As an operator, I want the command to load one predictable configuration file so that scheduled runs target the intended feed and room.

Acceptance criteria:

- The command reads `.env` in its current working directory. Only when that file is absent does it read `~/.chatto-rss-bridge.env` for the executing user.
- If neither file exists, or any required setting is absent or invalid, the command exits nonzero before fetching the feed or posting.
- Required settings are `BOT_API_KEY`, `BOT_ROOM_ID`, `BOT_RSS_SOURCE`, and `CHATTO_BASE_URL`. The base URL has no API path; the command adds the documented Chatto API path.
- Errors and normal output never reveal the API key.

## US-2: Read the configured RSS feed

As a reader, I want messages derived from actual feed episodes so that the room reflects the publisher's content.

Acceptance criteria:

- The command accepts a valid RSS feed and reads each item's GUID, title, publication date, description, and article link.
- It posts eligible episodes in publication order, oldest first, regardless of the feed's item order.
- An invalid feed, failed fetch, or item missing fields needed for safe identification or posting causes a visible nonzero failure without marking that item as seen.
- Feed descriptions are rendered as readable text, rather than raw XML or HTML markup.

## US-3: Post one root message per new episode

As a room member, I want one useful root-level message per episode so that I can read the summary and reply in a thread beneath it.

Acceptance criteria:

- Each posted message contains the episode title, a readable summary, and its article link.
- The command posts to `BOT_ROOM_ID` as the bot authenticated by `BOT_API_KEY` against `CHATTO_BASE_URL`.
- The command does not set a thread root or create a daily heading message.
- A successful response provides a Chatto message ID that is retained with the feed GUID in local state.

## US-4: Avoid routine repeat posts

As an operator, I want hourly runs to post only newly observed episodes so that the room stays free of repeated announcements.

Acceptance criteria:

- SQLite state survives process restarts and records each confirmed episode by feed GUID.
- A subsequent normal run skips recorded GUIDs and posts newly observed GUIDs in publication order.
- Overlapping invocations cannot post the same episode concurrently.
- A failed or unconfirmed post is not recorded as confirmed.

## US-5: Control the initial backlog

As an operator, I want a choice between replaying the visible feed and starting with today's episodes so that I can choose the room's initial volume.

Acceptance criteria:

- With an empty seen set, a normal run posts every current feed item, oldest first.
- With `--first-run`, the command posts only items published today in `Europe/Berlin` and marks every current feed GUID as seen, including older items it deliberately skipped.
- After either mode, later normal runs post only newly observed GUIDs.
- `--first-run` is an explicit run mode; it does not change future runs or require a separate configuration value.

## US-6: Reset feed history deliberately

As an operator, I want `--clear-feed` to clear the locally recorded seen GUIDs so that I can deliberately replay the current feed on the next run.

Acceptance criteria:

- `--clear-feed` does not fetch the feed or post to Chatto.
- It clears the seen records while preserving the SQLite database itself.
- The next normal run posts all items then present in the feed; the next run with `--first-run` follows that flag's today-only behavior.
- If an uncertain posting attempt is still pending, the reset exits with an error rather than silently discarding the pending attempt.

## US-7: Reconcile uncertain delivery

As an operator, I want an uncertain post checked against Chatto before retrying so that a lost response does not routinely duplicate an episode.

Acceptance criteria:

- The command records an attempt durably before sending an episode.
- On the next run after an uncertain result, it checks readable Chatto messages in the configured room for a post by this bot containing that episode's article link. It verifies candidate results against the full link and expected message content, rather than treating a search hit alone as proof.
- When a matching post exists, the command records its Chatto message ID and feed GUID without sending again.
- When a complete, reliable read establishes that no matching post exists, the command may retry. If the read is unavailable or inconclusive, it exits nonzero without retrying.
- Reconciliation applies to pending attempts. It does not suppress the intentional replay requested through `--clear-feed`.

## US-8: Operate the one-shot job safely

As an operator, I want a one-shot command that an hourly systemd timer can invoke with durable state and understandable failures.

Acceptance criteria:

- The command finishes after one feed check and reports success or a useful nonzero error; it does not run its own scheduler.
- The command supports a persistent writable SQLite location and the working directory or home directory needed for configuration discovery.
- Automated tests use controlled feed and Chatto responses; they never post to a live room.

## US-9: Maintain operator and developer documentation

As a server operator or developer, I want documentation aimed at my role so that I can deploy, operate, and maintain the bridge without guessing its setup or behavior.

Acceptance criteria:

- `README.md` targets the server operator. It explains the repository's purpose and the code's objective: poll the configured Presseschau RSS feed and post each new episode as a root message in a Chatto room.
- The README explains how to install the code and configure Chatto: create a bot, obtain its API key and stable room ID, add the bot to the room, and grant the effective post and read permissions needed for delivery and reconciliation.
- The README explains how to create the `.env` file with `BOT_API_KEY`, `BOT_ROOM_ID`, `BOT_RSS_SOURCE`, and `CHATTO_BASE_URL`, including the current-directory and home-directory lookup order, without publishing real credentials.
- The README explains the persistent SQLite state location, normal and `--first-run` behavior, `--clear-feed`, failures requiring operator attention, and hourly systemd timer operation.
- The first half of `AGENTS.md` addresses both human and agent developers: repository layout, local setup, development workflow, and required checks.
- The back part of `AGENTS.md` contains guardrails for agents only, including secret handling, external API verification, and avoiding live posts in automated tests. Instructions in the shared section are not repeated in the agent-only section, or vice versa.
- Both documents are updated when implementation changes their stated installation, configuration, operation, or development behavior.

## Planning assumptions to confirm before tickets

- The article link is the visible correlation marker, as in `chatto-releasebot`; the RSS GUID remains in SQLite and is not added as a visible footer.
- Chatto search is available on this server. The implementation may use it to find candidate messages, but a negative or unavailable search result must be handled so that an uncertain post is not retried on incomplete evidence.
- The precise message layout and SQLite file location can be selected during ticket planning without changing the behaviors above.
- `--clear-feed` is a standalone, non-posting command. It refuses to run while a pending attempt needs reconciliation.
