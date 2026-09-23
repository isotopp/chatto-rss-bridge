from pathlib import Path

import pytest

from chatto_rss_bridge import main


def test_command_reports_missing_configuration_without_leaking_key(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    working_directory = tmp_path / "work"
    home_directory = tmp_path / "home"
    working_directory.mkdir()
    home_directory.mkdir()
    (working_directory / ".env").write_text(
        "BOT_API_KEY=private-test-key\n", encoding="utf-8"
    )
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(Path, "home", lambda: home_directory)

    result = main([])

    captured = capsys.readouterr()
    assert result == 1
    assert "BOT_ROOM_ID" in captured.err
    assert "private-test-key" not in captured.out + captured.err
    assert captured.out == ""


def test_command_fails_when_neither_configuration_file_exists(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    working_directory = tmp_path / "work"
    home_directory = tmp_path / "home"
    working_directory.mkdir()
    home_directory.mkdir()
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(Path, "home", lambda: home_directory)

    result = main([])

    captured = capsys.readouterr()
    assert result == 1
    assert "configuration file not found" in captured.err
    assert captured.out == ""


def test_command_uses_home_configuration_when_working_file_is_absent(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    working_directory = tmp_path / "work"
    home_directory = tmp_path / "home"
    working_directory.mkdir()
    home_directory.mkdir()
    (home_directory / ".chatto-rss-bridge.env").write_text(
        "BOT_API_KEY=test-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://example.test/feed.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(Path, "home", lambda: home_directory)

    result = main([])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "Chatto RSS Bridge is not implemented yet.\n"
    assert captured.err == ""


def test_command_does_not_fill_missing_working_values_from_home(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    working_directory = tmp_path / "work"
    home_directory = tmp_path / "home"
    working_directory.mkdir()
    home_directory.mkdir()
    (working_directory / ".env").write_text(
        "BOT_API_KEY=working-key\n", encoding="utf-8"
    )
    (home_directory / ".chatto-rss-bridge.env").write_text(
        "BOT_API_KEY=home-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://example.test/feed.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(Path, "home", lambda: home_directory)

    result = main([])

    captured = capsys.readouterr()
    assert result == 1
    assert "BOT_ROOM_ID" in captured.err
    assert "home-key" not in captured.out + captured.err
    assert "working-key" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("CHATTO_BASE_URL", "https://chatto.example/api"),
        ("BOT_RSS_SOURCE", "ftp://example.test/feed.xml"),
    ],
)
def test_command_rejects_malformed_urls(
    monkeypatch, tmp_path: Path, capsys, setting: str, value: str
) -> None:
    values = {
        "BOT_API_KEY": "private-test-key",
        "BOT_ROOM_ID": "room-1",
        "BOT_RSS_SOURCE": "https://example.test/feed.xml",
        "CHATTO_BASE_URL": "https://chatto.example",
    }
    values[setting] = value
    (tmp_path / ".env").write_text(
        "\n".join(f"{name}={item}" for name, item in values.items()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = main([])

    captured = capsys.readouterr()
    assert result == 1
    assert setting in captured.err
    assert "private-test-key" not in captured.out + captured.err
