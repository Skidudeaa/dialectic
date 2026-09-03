"""ANNOTATOR_ENABLED (2026-09-02): the gate must read at call time and default on."""
from llm.annotator import annotator_enabled


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
