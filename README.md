# Chatto RSS Bridge

This project will poll the [Deutschlandfunk press review RSS feed](https://www.deutschlandfunk.de/presseschau-120.xml) on a schedule and post items to a Chatto channel using a [Chatto bot account](https://dev-docs.chatto.run/guides/integrations/bot-accounts/). The feed polling, scheduling, and Chatto integration are not implemented yet.

## Installation

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync
```

The project requires Python 3.14 or newer. `uv sync` installs the project and its development tools in `.venv`.

## Configuration

No runtime configuration is defined yet. A future bot will need feed, schedule, and Chatto channel settings and bot credentials. Keep credentials out of the repository.

## Operation

There is no operational bot yet. The current `uv run chatto-rss-bridge` command is a starter placeholder and does not fetch or post anything.

For development, run:

```sh
uv run ruff check --fix
uv run ruff format
uv run ty check
uv run pytest
```

The current test covers the starter command. Bot behavior tests will be added as that behavior is defined.
