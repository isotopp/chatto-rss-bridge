# Chatto RSS Bridge

Chatto RSS Bridge listens for direct mentions in one Chatto room and checks a
persistent set of RSS feeds. Manage feeds with room commands; run one
restartable service instead of a timer.

## Install

The server needs Python 3.14 or newer and [uv](https://docs.astral.sh/uv/).
Check out the repository at `/opt/chatto-rss-bridge`, then install the service:

```sh
cd /opt/chatto-rss-bridge
uv sync --no-dev
```

The command is installed at
`/opt/chatto-rss-bridge/.venv/bin/chatto-rss-bridge`.

## Configure Chatto

Create a bot account and add it to the destination room:

1. In Chatto, open **Server Admin → Bots → Create Bot**. Set a username and
   display name, then copy the API key from the creation dialog. Chatto shows
   the raw key only once.
2. Add the bot to the room. It needs effective `message.read` access to read
   room events and threads, and `message.post` access for RSS articles. The
   room must allow thread replies; Chatto also checks the applicable thread
   reply permission, such as `message.post`, `message.post-in-thread`, or an
   eligible interaction permission. The bot owner's permissions cap the bot's
   effective permissions.
3. Get the destination room's stable ID. Use the ID, not the room name.
4. Create or choose a Chatto role and assign the approved people to it. The
   role name must match `BOT_BRIDGE_ROLE` exactly.

The deployed bot key was verified to read its viewer ID, the configured room's
events, and users' roles. `UserService/GetUser` role checks do not require
admin access. Message and thread permissions are still required for the bot's
normal room work; see the [verified API contract](developer/2026-09-25-room-managed-feeds/integration-contract.md).

## Configure the service

Copy [`sample.env`](sample.env) to `.env` in the service working directory or
to `~/.chatto-rss-bridge.env` in the service account's home directory, then
replace the sample values:

```sh
cp sample.env .env
chmod 600 .env
```

| Variable | Value |
| --- | --- |
| `BOT_API_KEY` | The private API key copied when creating the bot. |
| `BOT_ROOM_ID` | The destination room's stable Chatto ID. |
| `BOT_BRIDGE_ROLE` | Exact Chatto role name required for `add`, `list`, and `delete`. |
| `CHATTO_BASE_URL` | Bare Chatto origin, such as `https://chatto.example`; no `/api` path. |

The command prefers `.env` in its current working directory. It reads the home
file only if `.env` is absent; an invalid `.env` does not fall back to the home
file. Keep the API key private, do not commit either configuration file, and
restrict it to the service account with mode `600`.

SQLite state is stored as `.chatto-rss-bridge.db` beside the configuration file
that was loaded. With the home configuration, this is
`~/.chatto-rss-bridge.db`. The database contains feed definitions, poll times,
seen articles, pending posts, and the realtime resume cursor. Back it up if you
need to preserve the bridge's history. Feeds and old delivery history are not
imported from the previous setup.

## Manage feeds

Mention the bot directly in the configured room. Replace `@rss-bot` below with
its Chatto mention:

```text
@rss-bot help
@rss-bot add presseschau https://www.deutschlandfunk.de/presseschau-120.xml 60
@rss-bot list
@rss-bot delete presseschau
```

`help` is available to any room member. `add`, `list`, and `delete` require the
sender's current membership in the role named by `BOT_BRIDGE_ROLE`; the bot
checks that role through Chatto for every command. `list` shows each feed's
name, URL, and interval.

An interval is in minutes and must be at least 10. When a feed is added, the
bot posts its most recent article to confirm the feed works, marks the articles
in that initial snapshot as seen, and then posts only new articles. Each feed
has its own interval and delivery history. Add the Presseschau manually with
the command above; its existing history is not migrated.

If an add's proof post has an uncertain response, repeat the same `add`
command. The bridge reconciles the pending post before retrying and does not
knowingly publish it twice. Feed fetch and posting errors are written to the
service log; other feeds continue to be checked.

## Run with systemd

Create a dedicated service account and private home for configuration and
SQLite state:

```sh
sudo useradd --system --user-group --home-dir /var/lib/chatto-rss-bridge --create-home --shell /usr/sbin/nologin chatto-rss-bridge
sudo install -o chatto-rss-bridge -g chatto-rss-bridge -m 600 sample.env /var/lib/chatto-rss-bridge/.chatto-rss-bridge.env
sudoedit /var/lib/chatto-rss-bridge/.chatto-rss-bridge.env
```

Create `/etc/systemd/system/chatto-rss-bridge.service`:

```ini
[Unit]
Description=Listen for Chatto RSS feed commands
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=chatto-rss-bridge
Environment=HOME=/var/lib/chatto-rss-bridge
WorkingDirectory=/opt/chatto-rss-bridge
ExecStart=/opt/chatto-rss-bridge/.venv/bin/chatto-rss-bridge
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Start the service, then add the Presseschau feed with a Chatto command:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now chatto-rss-bridge.service
systemctl status chatto-rss-bridge.service
journalctl -u chatto-rss-bridge.service
```

There is no timer unit. The service reconnects to Chatto and checks due feeds
while it runs. systemd restarts it after a failure; stopping it sends a graceful
shutdown signal.

Chatto resume cursors expire. If the service was disconnected too long to
resume, it logs that a gap may have missed commands and starts listening from
the current live boundary. Send any important command from that gap again; the
service never guesses old commands.
