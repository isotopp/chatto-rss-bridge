# Presseschau RSS posting tickets

Status: approved on 2026-09-23. Implementation is deferred until a separate request. These tickets derive from [user-stories.md](user-stories.md) and are ordered for one behavior-focused test and implementation cycle at a time.

The user-facing interface is the one-shot `chatto-rss-bridge` command, with `--first-run` and `--clear-feed` modes. Tests should exercise its observable results with temporary state and controlled feed and Chatto responses. Each completed code ticket runs the four repository checks and is committed before the next ticket.

Use `httpx` for feed and Chatto HTTP access unless a concrete incompatibility makes another approach necessary.

## 1. Resolve configuration and report errors safely

**Stories:** US-1. **Public interface:** `chatto-rss-bridge` with `.env` in the working directory or `~/.chatto-rss-bridge.env`.

- Read exactly one file, preferring the working-directory file; require `BOT_API_KEY`, `BOT_ROOM_ID`, `BOT_RSS_SOURCE`, and `CHATTO_BASE_URL`.
- Reject absent files, missing values, and malformed feed or base URLs before any feed fetch or Chatto post. Add the Chatto API path to the configured bare base URL when making requests.
- Keep the API key out of output and errors.
- **First failing check:** an empty temporary working directory and home produce a nonzero result with no HTTP requests; adding a valid home file permits the command to proceed, and adding a working-directory file takes precedence.

## 2. Publish one valid episode as a root message

**Stories:** US-2, US-3. **Public interface:** normal `chatto-rss-bridge` invocation.

- Fetch the configured RSS source, read one item with GUID, title, `pubDate`, description, and article link, and render title, readable summary, and link in the message body.
- Call Chatto `MessageService.CreateMessage` in `BOT_ROOM_ID` using the bot API key. Omit thread placement fields and require a response containing a message ID before reporting success.
- A denied post, transport failure, or malformed confirmation exits nonzero without claiming delivery. The command never prints the key.
- **First failing check:** a controlled one-item RSS response and fake Chatto response yield one authenticated root-message request whose body contains the episode title, summary, and article link.

## 3. Process the feed in publication order and reject unsafe input

**Stories:** US-2, US-3. **Public interface:** normal `chatto-rss-bridge` invocation against a multi-item feed.

- Post eligible items oldest first even when the RSS document is newest first; keep each item tied to its GUID.
- Turn description markup into readable text without posting raw XML or HTML.
- A failed fetch, invalid RSS document, or item missing a required identity or message field produces a visible nonzero error and does not mark that item as seen.
- **First failing check:** a controlled feed whose items are reversed by publication date produces root posts in chronological order, with plain-text summaries.

## 4. Persist confirmed deliveries and skip repeats

**Stories:** US-3, US-4. **Public interface:** repeated normal invocations using the same persistent state location.

- Store confirmed feed GUIDs and returned Chatto message IDs in SQLite. Use a persistent location suitable for an unattended user service, with an isolated temporary location available to tests.
- With empty state, post all items currently in the feed, oldest first. On later runs, skip confirmed GUIDs and post only new ones.
- A failed or unconfirmed item never appears as confirmed in state; database errors fail visibly rather than starting over.
- **First failing check:** the first run posts two controlled episodes and the second run against the same feed posts none; adding a third episode posts only that one.

## 5. Support the today-only `--first-run` mode

**Stories:** US-5. **Public interface:** `chatto-rss-bridge --first-run`.

- Compare item publication dates with the current date in `Europe/Berlin`, including around midnight and daylight-saving changes.
- Post only today's items, oldest first. Record older items in the current feed as deliberately seen; record today's posts as confirmed only after Chatto confirms them.
- Later normal runs skip the older items already seen and post new GUIDs.
- **First failing check:** a controlled feed spanning yesterday and today, with a fixed Berlin clock, posts only today's items and leaves a later normal run with no repeat posts.

## 6. Support deliberate replay with `--clear-feed`

**Stories:** US-6. **Public interface:** `chatto-rss-bridge --clear-feed`, followed by a normal run or `--first-run`.

- Clear seen GUIDs without fetching the feed or contacting Chatto. Keep the database usable.
- The next normal run posts the then-current feed again; the next `--first-run` applies its today-only rule.
- Refuse a reset while an uncertain posting attempt is pending, with a clear nonzero error.
- **First failing check:** after one confirmed post, `--clear-feed` makes no HTTP requests; the next normal invocation posts that episode again.

## 7. Preserve an uncertain attempt before sending

**Stories:** US-4, US-7. **Public interface:** normal invocation followed by another invocation after a simulated lost Chatto response.

- Record the GUID, article link, expected message body, and attempt status durably before calling `CreateMessage`.
- Treat timeouts and invalid success confirmations as uncertain. Leave the attempt pending, and never mark it confirmed without evidence.
- Until ticket 8 provides reconciliation, a later invocation seeing pending state fails safely rather than repeating the POST.
- **First failing check:** a fake Chatto transport accepts a request but drops its response; SQLite retains a pending attempt and the next run sends no duplicate.

## 8. Reconcile pending attempts through readable Chatto messages

**Stories:** US-7. **Public interface:** a normal invocation with a pending attempt in SQLite.

- Obtain the authenticated bot's user ID through Chatto `ViewerService.GetViewer`. Search the configured room for the pending episode's article link and verify any candidate's author and complete expected content before treating it as the bot's post.
- When found, store the matching Chatto message ID and GUID without posting again. If search is unavailable or finds no reliable match, inspect the room timeline as needed before deciding the post is absent.
- Retry only after a complete, reliable read establishes absence. A denied, unavailable, or incomplete read exits nonzero and leaves the attempt pending. Reconciliation applies only to pending attempts, so `--clear-feed` can deliberately replay confirmed items.
- **First failing check:** a pending item with a matching message in fake Chatto search is recorded as confirmed without a second `CreateMessage` request. Follow-up cycles cover reliable absence and inconclusive reads.

## 9. Prevent overlapping runs from posting the same item

**Stories:** US-4, US-8. **Public interface:** two concurrent normal `chatto-rss-bridge` invocations sharing one SQLite state location.

- Serialize the check, post, and state transition for a shared database. The second invocation sees the first invocation's confirmed or pending result.
- Failed runs release the lock so a later scheduled invocation can recover.
- **First failing check:** two controlled concurrent invocations observing one new episode produce at most one Chatto POST.

## 10. Maintain operator and developer guidance

**Stories:** US-8, US-9. **Public interface:** `README.md`, `AGENTS.md`, and a credential-free sample configuration.

- Explain the project's purpose and objective, installation, Chatto bot creation and API key retrieval, room ID discovery, room membership, effective post/read permissions, and `.env` creation and lookup order.
- Document the persistent SQLite location, hourly systemd timer setup, first-run and clear-feed modes, pending failures, and safe operation without exposing real credentials.
- Keep the first half of `AGENTS.md` for human and agent development instructions. Keep agent-only guardrails in the back part, without repeating instructions across halves.
- **First failing check:** an operator can follow the documented setup with placeholder credentials and identify every required value, permission, state path, command, and recovery action; documentation examples contain no live key.

## External contracts to verify during implementation

- [Deutschlandfunk Presseschau feed](https://www.deutschlandfunk.de/presseschau-120.xml): RSS 2.0 episodes with GUID, title, publication date, description, and article link in the sampled feed.
- [Chatto MessageService](https://dev-docs.chatto.run/reference/connectrpc-api/messages/): root message creation and confirmation ID.
- [Chatto ViewerService](https://dev-docs.chatto.run/reference/connectrpc-api/viewer/), [MessageSearchService](https://dev-docs.chatto.run/reference/connectrpc-api/message-search/), and [RoomService](https://dev-docs.chatto.run/reference/connectrpc-api/rooms/): bot identity and readback for uncertain posts. The referenced development docs describe unreleased changes; verify the deployed server's behavior with read-only calls before depending on these contracts.
