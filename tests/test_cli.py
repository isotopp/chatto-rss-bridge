from chatto_rss_bridge import main


def test_cli_reports_unimplemented_state(capsys) -> None:
    main()

    assert capsys.readouterr().out == "Chatto RSS Bridge is not implemented yet.\n"
