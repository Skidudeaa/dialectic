"""
Tests for the book <-> Dialectic room join key exposed by /api/thesis/books.

WHY: Dialectic's "Open Full Dashboard" link carries the room the user was
arguing in. The desk resolves that room to the book it discusses so the user
lands on the right case. That resolution depends on list_books() exposing
meta.dialecticRoomId — and on it NEVER exposing meta.dialecticRoomToken,
which is a room credential.
"""

import json
import os

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.adapters import thesis as thesis_adapter


def _write_book(tmp_path, monkeypatch, name, meta):
    books_dir = tmp_path / "books"
    books_dir.mkdir(exist_ok=True)
    (books_dir / f"{name}-graph.json").write_text(
        json.dumps({"meta": meta, "nodes": [], "edges": []})
    )
    monkeypatch.setattr(thesis_adapter, "BOOKS_DIR", books_dir)
    return books_dir


class TestRoomJoinKey:
    def test_exposes_dialectic_room_id(self, tmp_path, monkeypatch):
        _write_book(
            tmp_path,
            monkeypatch,
            "acme",
            {"title": "Acme Thesis", "dialecticRoomId": "room-uuid-123"},
        )
        books = thesis_adapter.list_books()

        assert len(books) == 1
        assert books[0]["dialecticRoomId"] == "room-uuid-123"

    def test_never_exposes_the_room_token(self, tmp_path, monkeypatch):
        """The token is a room credential. The id is a join key. Only one of
        them may reach a browser."""
        _write_book(
            tmp_path,
            monkeypatch,
            "acme",
            {
                "title": "Acme Thesis",
                "dialecticRoomId": "room-uuid-123",
                "dialecticRoomToken": "super-secret-room-token",
            },
        )
        books = thesis_adapter.list_books()

        serialized = json.dumps(books)
        assert "super-secret-room-token" not in serialized
        assert not any("oken" in key for key in books[0])

    def test_book_without_a_linked_room_yields_none(self, tmp_path, monkeypatch):
        """Unlinked books must still list — the deep link simply won't resolve
        to them, and the desk falls back to its own default."""
        _write_book(tmp_path, monkeypatch, "orphan", {"title": "Orphan Thesis"})
        books = thesis_adapter.list_books()

        assert books[0]["dialecticRoomId"] is None
        assert books[0]["title"] == "Orphan Thesis"

    def test_existing_fields_are_unchanged(self, tmp_path, monkeypatch):
        """The new key is additive; the desk's existing rendering must not move."""
        _write_book(
            tmp_path,
            monkeypatch,
            "acme",
            {"title": "Acme Thesis", "dialecticRoomId": "room-uuid-123"},
        )
        book = thesis_adapter.list_books()[0]

        assert book["id"] == "acme-graph"
        assert book["filename"] == "acme-graph.json"
        assert book["title"] == "Acme Thesis"
        assert book["nodes"] == 0
        assert book["edges"] == 0


class TestAgainstRealBooks:
    """The join key is only useful if the REAL books carry it — a synthetic
    fixture would pass just as happily against an empty production corpus."""

    def test_live_books_expose_room_ids(self):
        books = thesis_adapter.list_books()
        if not books:
            import pytest

            pytest.skip("no book configs on this host")

        linked = [b for b in books if b.get("dialecticRoomId")]
        assert linked, "no book carries a dialecticRoomId — deep link cannot resolve"

    def test_live_books_leak_no_token(self):
        books = thesis_adapter.list_books()
        assert not any("oken" in key for b in books for key in b)
