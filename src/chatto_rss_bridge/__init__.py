import argparse
import sys
from collections.abc import Sequence

import httpx

from .chatto import ChattoError
from .config import Config, ConfigError
from .rss import FeedError
from .runner import run_once
from .state import StateError


def main(
    argv: Sequence[str] | None = None, *, http_client: httpx.Client | None = None
) -> int:
    parser = argparse.ArgumentParser(prog="chatto-rss-bridge")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--first-run", action="store_true")
    mode.add_argument("--clear-feed", action="store_true")
    args = parser.parse_args(argv)
    try:
        message = run_once(
            Config.load(),
            http_client=http_client,
            first_run=args.first_run,
            clear_feed=args.clear_feed,
        )
    except (ChattoError, ConfigError, FeedError, StateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0
