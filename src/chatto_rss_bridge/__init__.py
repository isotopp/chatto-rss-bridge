import argparse
import sys
from collections.abc import Sequence

from .config import Config, ConfigError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatto-rss-bridge")
    parser.parse_args(argv)
    try:
        Config.load()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Chatto RSS Bridge is not implemented yet.")
    return 0
