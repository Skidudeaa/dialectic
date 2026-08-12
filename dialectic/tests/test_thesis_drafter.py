"""
Contracts for llm/thesis_drafter.py — the proposal machine behind the
Create Thesis draft flow.

The validator is the load-bearing piece: everything it misses goes straight
into a live book on tradingDesk when the human taps Accept, so these tests
lean on the reject side. The model call is mocked at llm.providers.get_provider;
the retry contract (one correction pass, then DraftError) is pinned because
the endpoint's 502 semantics depend on it.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from llm.thesis_drafter import (
    DraftError,
    draft_thesis_graph,
    validate_draft,
)


def good_draft() -> dict:
    return {
        "rationale": "Shock hits shipping first; the reversal is a truce.",
        "nodes": [
            {"id": "shock", "label": "The Shock", "type": "event", "phase": 1,
             "context": "The triggering state."},
            {"id": "crude", "label": "Crude Spike", "type": "price", "phase": 2,
             "context": "First-order pass-through.",
             "thresholds": [{"level": 100, "label": "regime break"}]},
            {"id": "freight", "label": "Freight Stress", "type": "indicator",
             "phase": 2, "context": "Costs transmit.",
             "feeds": [{"source": "yahoo", "symbol": "BDRY", "label": "Baltic Dry"}]},
            {"id": "truce", "label": "De-escalation", "type": "reversal",
             "phase": 5, "context": "What kills the thesis."},
        ],
        "edges": [
            {"source": "shock", "target": "crude",
             "mechanism": "20% of supply disrupted", "lag": "immediate",
             "strength": 0.9},
            {"source": "crude", "target": "freight",
             "mechanism": "bunker fuel cost pass-through", "lag": "1-2 weeks",
             "strength": 0.7},
        ],
    }


class TestValidator:
    def test_a_good_draft_passes(self):
        assert validate_draft(good_draft()) == []

    def test_cycle_is_fatal(self):
        d = good_draft()
        d["edges"].append({"source": "freight", "target": "shock",
                           "mechanism": "feedback", "lag": "1 month",
                           "strength": 0.5})
        d["edges"].append({"source": "crude", "target": "shock",
                           "mechanism": "x", "lag": "y", "strength": 0.5})
        errors = validate_draft(d)
        assert any("cycle" in e for e in errors)

    def test_dangling_edge_is_rejected(self):
        d = good_draft()
        d["edges"].append({"source": "shock", "target": "ghost",
                           "mechanism": "x", "lag": "y", "strength": 0.5})
        assert any("unknown node" in e for e in validate_draft(d))

    def test_duplicate_ids_are_rejected(self):
        d = good_draft()
        d["nodes"].append(dict(d["nodes"][0]))
        assert any("duplicate node id" in e for e in validate_draft(d))

    def test_self_loop_is_rejected(self):
        d = good_draft()
        d["edges"].append({"source": "crude", "target": "crude",
                           "mechanism": "x", "lag": "y", "strength": 0.5})
        assert any("self-loop" in e for e in validate_draft(d))

    def test_unknown_type_and_phase_are_rejected(self):
        d = good_draft()
        d["nodes"][0]["type"] = "vibes"
        d["nodes"][1]["phase"] = 9
        errors = validate_draft(d)
        assert any("type" in e for e in errors)
        assert any("phase" in e for e in errors)

    def test_too_few_nodes_is_rejected(self):
        d = good_draft()
        d["nodes"] = d["nodes"][:2]
        d["edges"] = d["edges"][:1]
        assert any("node count" in e for e in validate_draft(d))

    def test_strength_out_of_range_is_rejected(self):
        d = good_draft()
        d["edges"][0]["strength"] = 1.4
        assert any("strength" in e for e in validate_draft(d))

    def test_guessed_feed_sources_are_rejected(self):
        """The prompt says yahoo/fred or omit — a hallucinated source must
        not ride into a live book's fetch config."""
        d = good_draft()
        d["nodes"][2]["feeds"] = [{"source": "bloomberg", "symbol": "XYZ"}]
        assert any("feeds" in e for e in validate_draft(d))

    def test_non_object_draft_is_rejected(self):
        assert validate_draft([1, 2]) != []
        assert validate_draft(None) != []


def _provider_returning(*contents: str):
    """Stub provider whose complete() answers each content in turn."""
    responses = [SimpleNamespace(content=c) for c in contents]
    provider = SimpleNamespace(complete=AsyncMock(side_effect=responses))
    return provider


@pytest.mark.asyncio
class TestDraftCall:
    async def test_good_json_is_sanitized_and_laid_out(self, monkeypatch):
        provider = _provider_returning(json.dumps(good_draft()))
        monkeypatch.setattr("llm.providers.get_provider", lambda *_: provider)

        draft = await draft_thesis_graph("T", "C", 5000)

        assert len(draft["nodes"]) == 4
        # Runtime facts are stripped: every node starts monitoring.
        assert all(n["state"] == "monitoring" for n in draft["nodes"])
        # Phase-column layout: both phase-2 nodes share x, stacked y.
        crude, freight = draft["nodes"][1], draft["nodes"][2]
        assert crude["x"] == freight["x"] == 280 + 100
        assert crude["y"] != freight["y"]
        assert draft["rationale"].startswith("Shock hits")

    async def test_fenced_json_is_tolerated(self, monkeypatch):
        provider = _provider_returning(
            "```json\n" + json.dumps(good_draft()) + "\n```"
        )
        monkeypatch.setattr("llm.providers.get_provider", lambda *_: provider)
        draft = await draft_thesis_graph("T", "C", 5000)
        assert len(draft["edges"]) == 2

    async def test_invalid_first_try_gets_one_correction_pass(self, monkeypatch):
        bad = good_draft()
        bad["edges"].append({"source": "freight", "target": "shock",
                             "mechanism": "feedback", "lag": "x",
                             "strength": 0.5})
        bad["edges"].append({"source": "crude", "target": "shock",
                             "mechanism": "x", "lag": "y", "strength": 0.5})
        provider = _provider_returning(json.dumps(bad), json.dumps(good_draft()))
        monkeypatch.setattr("llm.providers.get_provider", lambda *_: provider)

        draft = await draft_thesis_graph("T", "C", 5000)

        assert provider.complete.await_count == 2
        # The retry carried the validator's verdict back to the model.
        retry_request = provider.complete.await_args_list[1].args[0]
        retry_text = retry_request.messages[-1]["content"]
        assert "failed validation" in retry_text and "cycle" in retry_text
        assert len(draft["nodes"]) == 4

    async def test_two_failures_raise_draft_error(self, monkeypatch):
        provider = _provider_returning("not json at all", "still not json")
        monkeypatch.setattr("llm.providers.get_provider", lambda *_: provider)
        with pytest.raises(DraftError):
            await draft_thesis_graph("T", "C", 5000)
        assert provider.complete.await_count == 2
