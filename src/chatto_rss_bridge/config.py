from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    room_id: str
    rss_source: str
    chatto_base_url: str
    state_path: Path
    bot_bridge_role: str

    @classmethod
    def load(cls, *, cwd: Path | None = None, home: Path | None = None) -> Config:
        working_file = (cwd or Path.cwd()) / ".env"
        home_file = (home or Path.home()) / ".chatto-rss-bridge.env"
        if working_file.exists():
            config_file = working_file
        elif home_file.exists():
            config_file = home_file
        else:
            raise ConfigError("configuration file not found")
        if not config_file.is_file():
            raise ConfigError("configuration path is not a regular file")
        try:
            values = dotenv_values(config_file, interpolate=False)
        except (OSError, UnicodeError) as exc:
            raise ConfigError("could not read configuration file") from exc

        required = {
            "BOT_API_KEY": values.get("BOT_API_KEY"),
            "BOT_ROOM_ID": values.get("BOT_ROOM_ID"),
            "BOT_BRIDGE_ROLE": values.get("BOT_BRIDGE_ROLE"),
            "CHATTO_BASE_URL": values.get("CHATTO_BASE_URL"),
        }
        cleaned = {
            name: value.strip()
            for name, value in required.items()
            if isinstance(value, str) and value.strip()
        }
        missing = [name for name in required if name not in cleaned]
        if missing:
            raise ConfigError(f"missing required configuration: {', '.join(missing)}")
        api_key = cleaned["BOT_API_KEY"]
        room_id = cleaned["BOT_ROOM_ID"]
        bot_bridge_role = cleaned["BOT_BRIDGE_ROLE"]
        legacy_rss_source = values.get("BOT_RSS_SOURCE")
        rss_source = (
            legacy_rss_source.strip() if isinstance(legacy_rss_source, str) else ""
        )
        chatto_base_url = cleaned["CHATTO_BASE_URL"].rstrip("/")
        if rss_source:
            _validate_url("BOT_RSS_SOURCE", rss_source, allow_path=True)
        _validate_url("CHATTO_BASE_URL", chatto_base_url, allow_path=False)
        return cls(
            api_key,
            room_id,
            rss_source,
            chatto_base_url,
            config_file.with_name(".chatto-rss-bridge.db"),
            bot_bridge_role,
        )


def _validate_url(name: str, value: str, *, allow_path: bool) -> None:
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and parts.port != 0
            and not parts.fragment
            and (allow_path or (parts.path in {"", "/"} and not parts.query))
        )
    except ValueError:
        valid = False
    if not valid:
        url_type = "URL" if allow_path else "bare URL"
        raise ConfigError(f"{name} must be a valid {url_type}")
