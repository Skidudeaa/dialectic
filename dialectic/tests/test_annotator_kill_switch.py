"""ANNOTATOR_ENABLED (2026-09-02): the gate must read at call time and default on."""
from llm.annotator import annotator_enabled
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from tests.conftest import make_message, ROOM_ID, THREAD_ID


def test_default_on(monkeypatch):
    monkeypatch.delenv("ANNOTATOR_ENABLED", raising=False)
    assert annotator_enabled() is True


def test_zero_silences(monkeypatch):
    monkeypatch.setenv("ANNOTATOR_ENABLED", "0")
    assert annotator_enabled() is False


def test_handler_consults_the_switch():
    # The handler's gate is one expression; pin that it names the switch so a
    # refactor cannot drop it silently.
    src = open("transport/handlers.py").read()
    assert "if member_count >= 2 and annotator_enabled():" in src


@pytest.mark.asyncio
async def test_annotation_is_a_bounded_connection_if_reenabled(monkeypatch):
    from llm.annotator import AnnotatorEngine
    import llm.providers as providers
    import operations

    message = make_message("This claim contradicts our earlier position.")
    provider = SimpleNamespace(complete=AsyncMock(return_value=SimpleNamespace(
        content="This conflicts with the room's earlier claim. " * 30,
    )))
    monkeypatch.setattr(providers, "get_provider", lambda _: provider)
    monkeypatch.setattr(operations, "get_thread_messages", AsyncMock(return_value=[message]))
    db = SimpleNamespace(fetch=AsyncMock(return_value=[]),
                         fetchrow=AsyncMock(return_value={"sequence": 2}), execute=AsyncMock())
    annotation = await AnnotatorEngine(db, None, None).annotate(
        ROOM_ID, THREAD_ID, message, related=[{"key": "prior", "content": "Earlier position"}],
    )
    assert annotation is not None
    assert 0 < len(annotation.content.split()) <= 24
    assert annotation.content.endswith("…")
    assert db.fetchrow.call_args.args[-1] == annotation.content
    assert provider.complete.call_args.args[0].max_tokens == 192
