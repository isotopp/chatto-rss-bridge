from pathlib import Path

import pytest

from chatto_rss_bridge.state import (
    FeedExistsError,
    FeedNotFoundError,
    FeedPendingAttempt,
    FeedStore,
    SeenStore,
    StateError,
)


def test_named_feed_can_be_added_found_listed_and_reopened(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = FeedStore(path)
    try:
        added = store.add_feed("briefing", "https://example.test/rss", 15)
        assert added.name == "briefing"
        assert store.get_feed("briefing") == added
        assert store.list_feeds() == [added]
    finally:
        store.close()

    reopened = FeedStore(path)
    try:
        assert reopened.get_feed("briefing") == added
        assert reopened.list_feeds() == [added]
    finally:
        reopened.close()


def test_duplicate_feed_name_is_rejected_without_replacing_existing_feed(
    tmp_path: Path,
) -> None:
    store = FeedStore(tmp_path / "state.db")
    try:
        store.add_feed("briefing", "https://example.test/first.xml", 15)
        with pytest.raises(FeedExistsError):
            store.add_feed("briefing", "https://example.test/second.xml", 30)
        assert store.get_feed("briefing").url == "https://example.test/first.xml"
    finally:
        store.close()


def test_unknown_feed_is_reported_by_find_and_delete(tmp_path: Path) -> None:
    store = FeedStore(tmp_path / "state.db")
    try:
        with pytest.raises(FeedNotFoundError):
            store.get_feed("missing")
        with pytest.raises(FeedNotFoundError):
            store.delete_feed("missing")
    finally:
        store.close()


def test_interval_below_ten_minutes_is_rejected(tmp_path: Path) -> None:
    store = FeedStore(tmp_path / "state.db")
    try:
        with pytest.raises(StateError):
            store.add_feed("briefing", "https://example.test/rss", 9)
        assert store.list_feeds() == []
    finally:
        store.close()


def test_seen_and_pending_article_state_is_feed_scoped_and_persistent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.db"
    store = FeedStore(path)
    store.add_feed("alpha", "https://example.test/a.xml", 10)
    store.add_feed("beta", "https://example.test/b.xml", 20)
    store.mark_seen("alpha", "shared-guid")
    for feed_name in ("alpha", "beta"):
        store.begin_attempt(
            feed_name,
            "pending-guid",
            "https://example.test/article",
            "Article body",
        )

    assert store.contains("alpha", "shared-guid")
    assert not store.contains("beta", "shared-guid")
    assert store.pending_attempts() == [
        FeedPendingAttempt(
            "alpha", "pending-guid", "https://example.test/article", "Article body"
        ),
        FeedPendingAttempt(
            "beta", "pending-guid", "https://example.test/article", "Article body"
        ),
    ]
    store.confirm("alpha", "pending-guid", "chatto-message-alpha")
    store.close()

    reopened = FeedStore(path)
    try:
        assert reopened.contains("alpha", "shared-guid")
        assert not reopened.contains("beta", "shared-guid")
        assert reopened.contains("alpha", "pending-guid")
        assert not reopened.contains("beta", "pending-guid")
        assert reopened.pending_attempts() == [
            FeedPendingAttempt(
                "beta", "pending-guid", "https://example.test/article", "Article body"
            )
        ]
    finally:
        reopened.close()


def test_deleted_feed_can_be_added_again_without_its_old_history(
    tmp_path: Path,
) -> None:
    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", "https://example.test/rss", 10)
    store.mark_seen("briefing", "old-guid", "old-message")

    store.delete_feed("briefing")
    assert store.list_feeds() == []
    with pytest.raises(FeedNotFoundError):
        store.get_feed("briefing")

    store.add_feed("briefing", "https://example.test/new.xml", 20)
    assert not store.contains("briefing", "old-guid")
    store.close()


def test_feed_with_pending_post_cannot_be_deleted(tmp_path: Path) -> None:
    store = FeedStore(tmp_path / "state.db")
    store.add_feed("briefing", "https://example.test/rss", 10)
    store.begin_attempt(
        "briefing", "uncertain-guid", "https://example.test/article", "Article"
    )

    with pytest.raises(StateError, match="pending"):
        store.delete_feed("briefing")
    assert store.get_feed("briefing").name == "briefing"
    assert len(store.pending_attempts("briefing")) == 1
    store.close()


def test_named_feed_store_does_not_import_legacy_seen_history(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    legacy = SeenStore(path)
    legacy.confirm("legacy-guid", "legacy-message")
    legacy.close()

    store = FeedStore(path)
    try:
        store.add_feed("briefing", "https://example.test/rss", 10)
        assert store.list_feeds()[0].name == "briefing"
        assert not store.contains("briefing", "legacy-guid")
    finally:
        store.close()
