# Chatto RSS Bridge

This project will poll the [Deutschlandfunk press review RSS feed](https://www.deutschlandfunk.de/presseschau-120.xml) on a schedule and post items to a Chatto channel using a [Chatto bot account](https://dev-docs.chatto.run/guides/integrations/bot-accounts/). The feed polling, scheduling, and Chatto integration are not implemented yet.

## Installation

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync
```

The project requires Python 3.14 or newer. `uv sync` installs the project and its development tools in `.venv`.

## Configuration

The command reads `.env` from its current directory. If that file is absent, it reads `~/.chatto-rss-bridge.env`; if neither exists or a required value is missing, it exits with an error. The required values are `BOT_API_KEY`, `BOT_ROOM_ID`, `BOT_RSS_SOURCE`, and `CHATTO_BASE_URL`. See [sample.env](sample.env) for the shape of the file, and keep real credentials out of the repository.

## Operation

The command fetches and posts a feed containing exactly one item. Multi-item feed handling and repeat suppression are still being implemented.

For development, run:

```sh
uv run ruff check --fix
uv run ruff format
uv run ty check
uv run pytest
```

The current test covers the starter command. Bot behavior tests will be added as that behavior is defined.
