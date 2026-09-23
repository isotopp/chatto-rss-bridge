# Chatto RSS Bridge

Chatto RSS Bridge checks the [Deutschlandfunk Presseschau RSS feed](https://www.deutschlandfunk.de/presseschau-120.xml) and posts each new episode to one Chatto room as a root-level message. Readers can start threads beneath an episode to discuss it. Run the command on a schedule; the recommended hourly interval is sufficient for the four daily editions.

## Install

The server needs Python 3.14 or newer and [uv](https://docs.astral.sh/uv/). Check out the [repository](https://github.com/isotopp/chatto-rss-bridge) at `/opt/chatto-rss-bridge`, then install the application:

```sh
cd /opt/chatto-rss-bridge
uv sync --no-dev
```

The command is installed at `/opt/chatto-rss-bridge/.venv/bin/chatto-rss-bridge`.

## Configure Chatto

Create a bot account and add it to the destination room before configuring this bridge:

1. In Chatto, open **Server Admin → Bots → Create Bot**. Set a username and display name, then copy the API key from the creation dialog. Chatto shows the raw key only once; store it in the private configuration file below.
2. Open the bot's detail page. Grant `room.join` for the destination room, then add the bot in the **Joined** row. Alternatively, an administrator with `room.manage` for that room or `user.manage-accounts` can add it without granting `room.join`.
3. Grant the bot effective `message.post` and `message.read` permissions for that room. `message.post` allows the root posts this bridge sends. `message.read` lets it search and inspect the room timeline to reconcile a post when a request times out. Room membership alone does not grant message access. The bot owner's effective permissions cap the bot's permissions, so the owner must also be allowed these actions.
4. Get the destination room's stable ID. Use the room details if your Chatto client exposes it; otherwise ask a server administrator to retrieve it from the room record. Use the ID, not the room name.

See Chatto's [Bot Accounts guide](https://dev-docs.chatto.run/guides/integrations/bot-accounts/) for the current account and permission controls. That page may describe a development build; confirm the equivalent controls are available in your deployed Chatto version.

## Configure this bridge

Copy [`sample.env`](sample.env) to `.env` in the directory where the command will run, then replace the sample values:

```sh
cp sample.env .env
chmod 600 .env
```

For an unattended systemd service, the recommended location is `~/.chatto-rss-bridge.env` in the service account's home directory. The command prefers `.env` in its current working directory. Only when that file is absent does it read `~/.chatto-rss-bridge.env`; a present but invalid `.env` does not fall back to the home file. For the systemd example below, leave `/opt/chatto-rss-bridge/.env` absent so the service uses its home configuration.

| Variable | Value |
| --- | --- |
| `BOT_API_KEY` | The bot API key copied when creating the bot. |
| `BOT_ROOM_ID` | The destination room's stable Chatto ID. |
| `BOT_RSS_SOURCE` | The feed URL; the Presseschau feed is in `sample.env`. |
| `CHATTO_BASE_URL` | The bare Chatto origin, such as `https://chatto.example`. Do not append `/api` or another path. |

Keep the API key private. Do not commit `.env` or `~/.chatto-rss-bridge.env`, paste the key into a command, or include it in logs or screenshots. Restrict the file to the service account with mode `600`.

SQLite state is stored beside the configuration file that was loaded. With a working-directory `.env`, the database is `.chatto-rss-bridge.db` in that directory; with the home fallback, it is `~/.chatto-rss-bridge.db`. The adjacent lock file coordinates overlapping runs. Back up the database if you need to preserve the bridge's delivery history.

## Operate

Run `chatto-rss-bridge` once to fetch the feed and publish unseen episodes, oldest first. Descriptions are rendered as plain text. Confirmed episode GUIDs and Chatto message IDs are persisted, so later runs skip them.

The first normal run posts every item currently in the feed. To limit initial posts, run `chatto-rss-bridge --first-run`: it posts only episodes whose publication date is today in `Europe/Berlin` and marks older items currently in the feed as seen. Use `chatto-rss-bridge --clear-feed` by itself only when you intend to replay the current feed; it clears seen history without contacting Chatto or the feed, and refuses while a post attempt is pending.

If Chatto may have accepted a post but the bridge did not receive a valid confirmation, the attempt remains pending. A later run searches Chatto and inspects the room timeline before retrying. If those reads are denied, unavailable, or incomplete, the run exits with an error and keeps the pending attempt for recovery. Fix the bot's read permissions or Chatto availability, then run the command again; do not delete the database to clear a pending attempt.

## Run hourly with systemd

Create a dedicated service account and give it a private home for configuration and SQLite state:

```sh
sudo useradd --system --user-group --home-dir /var/lib/chatto-rss-bridge --create-home --shell /usr/sbin/nologin chatto-rss-bridge
sudo install -o chatto-rss-bridge -g chatto-rss-bridge -m 600 sample.env /var/lib/chatto-rss-bridge/.chatto-rss-bridge.env
sudoedit /var/lib/chatto-rss-bridge/.chatto-rss-bridge.env
```

Run `sudoedit /etc/systemd/system/chatto-rss-bridge.service` and save:

```ini
[Unit]
Description=Post new Deutschlandfunk Presseschau episodes to Chatto
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=chatto-rss-bridge
Environment=HOME=/var/lib/chatto-rss-bridge
WorkingDirectory=/opt/chatto-rss-bridge
ExecStart=/opt/chatto-rss-bridge/.venv/bin/chatto-rss-bridge
```

Run `sudoedit /etc/systemd/system/chatto-rss-bridge.timer` and save:

```ini
[Unit]
Description=Check the Presseschau feed hourly

[Timer]
OnCalendar=hourly
Persistent=true
Unit=chatto-rss-bridge.service

[Install]
WantedBy=timers.target
```

Before enabling the timer, use the service account for the initial today-only run so the first scheduled run does not publish the entire current feed:

```sh
sudo -u chatto-rss-bridge -H sh -c 'cd /opt/chatto-rss-bridge && .venv/bin/chatto-rss-bridge --first-run'
```

Then activate and inspect the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now chatto-rss-bridge.timer
systemctl list-timers chatto-rss-bridge.timer
journalctl -u chatto-rss-bridge.service
```

The service reads its `.env` file directly; use the home-file path shown above rather than relying on a systemd `EnvironmentFile=`. The SQLite database will be `/var/lib/chatto-rss-bridge/.chatto-rss-bridge.db`.
