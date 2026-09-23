from pathlib import Path

from chatto_rss_bridge import main


def test_cli_reports_unimplemented_state(monkeypatch, tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text(
        "BOT_API_KEY=test-key\n"
        "BOT_ROOM_ID=room-1\n"
        "BOT_RSS_SOURCE=https://example.test/feed.xml\n"
        "CHATTO_BASE_URL=https://chatto.example\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    main()

    assert capsys.readouterr().out == "Chatto RSS Bridge is not implemented yet.\n"
