# Chatto RSS Bridge

This project reads the [Deutschlandfunk press review RSS feed](https://www.deutschlandfunk.de/presseschau-120.xml) and posts items to a Chatto channel using a [Chatto bot account](https://dev-docs.chatto.run/guides/integrations/bot-accounts/). The command can be run on a schedule; persistent repeat suppression and systemd setup are still being implemented.

## Installation

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync
```

The project requires Python 3.14 or newer. `uv sync` installs the project and its development tools in `.venv`.

## Configuration

The command reads `.env` from its current directory. If that file is absent, it reads `~/.chatto-rss-bridge.env`; if neither exists or a required value is missing, it exits with an error. The required values are `BOT_API_KEY`, `BOT_ROOM_ID`, `BOT_RSS_SOURCE`, and `CHATTO_BASE_URL`. See [sample.env](sample.env) for the shape of the file, and keep real credentials out of the repository. The SQLite database `.chatto-rss-bridge.db` is stored beside the configuration file that was loaded.

## Operation

The command validates the feed, then posts unseen items as root messages in publication order, oldest first. HTML in descriptions is rendered as plain text. Confirmed GUIDs and Chatto message IDs are stored in the SQLite database; later runs skip confirmed items.

For development, run:

```sh
uv run ruff check --fix
uv run ruff format
uv run ty check
uv run pytest
```

The tests use controlled RSS and Chatto responses; they do not post to a live channel.
