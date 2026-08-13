# tests/test_tools_registry.py — tool registry contracts + tradingDesk client

import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from llm import cairn_client as cn
from llm import defuddle_client as dc
from llm import tools as tools_mod
from llm import tradingdesk_client as td
from llm.tools import Tool, ToolRegistry, build_registry, resolve_book_id
from memory.vector_store import SimilarityMatch


NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

EXPECTED_TOOLS = {
    "get_live_quotes",
    "get_polymarket_odds",
    "get_thesis_state",
    "diff_thesis_last_hour",
    "evaluate_scenario",
    "get_open_trades",
    "get_morning_brief",
    "get_thesis_news",
    "search_memories",
    "search_transcript",
    "draft_prediction",
    "propose_thesis",
    "read_article",
    "save_reading",
    "search_reading",
    "search_dev_sessions",
    "recent_dev_activity",
    "get_dev_session",
    "search_dev_insights",
}


class FakeDB:
    """Minimal asyncpg-connection stand-in: scripted rows per fetch()."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.queries: list[tuple] = []

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        if callable(self.rows):
            return self.rows(query, args)
        return self.rows


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def registry(room, db):
    return build_registry(room, db)


# ── registry shape ───────────────────────────────────────────────────


class TestRegistryContract:
    def test_registers_all_nineteen_tools(self, registry):
        assert set(registry.names()) == EXPECTED_TOOLS
        assert len(registry.tools) == 19

    def test_names_match_anthropic_pattern(self, registry):
        for tool in registry.tools:
            assert NAME_RE.match(tool.name), f"bad tool name: {tool.name!r}"

    def test_schemas_are_valid_json_schema_objects(self, registry):
        for schema in registry.schemas():
            assert set(schema) == {"name", "description", "input_schema"}
            body = schema["input_schema"]
            assert body["type"] == "object"
            assert isinstance(body.get("properties"), dict)
            for prop in body["properties"].values():
                assert "type" in prop
            for required in body.get("required", []):
                assert required in body["properties"]

    def test_descriptions_teach_when_to_use(self, registry):
        """A bare restatement of the name teaches the model nothing."""
        for tool in registry.tools:
            assert len(tool.description) > 80
            assert "Use" in tool.description or "use" in tool.description

    def test_labels_are_human_phrases(self, registry):
        labels = registry.labels()
        assert set(labels) == EXPECTED_TOOLS
        for name, label in labels.items():
            assert label.strip()
            # Rendered mid-sentence in the UI ("Claude is checking live prices"),
            # so it must read as a phrase: lowercase opener, no full stop.
            assert label[0].islower(), f"{name} label should not start capitalised"
            assert not label.endswith("."), f"{name} label should not be a sentence"

    def test_get_returns_none_for_unknown(self, registry):
        assert registry.get("get_live_quotes") is not None
        assert registry.get("delete_everything") is None

    def test_no_tool_performs_a_server_write(self, registry):
        """Read-only by design — no ui.* broadcasts, no mutations. The one
        exception shape is draft_prediction, a PROPOSAL: its executor
        validates and shapes the draft but writes nothing; the write is the
        human's Accept tap (api/prediction_relay.py), outside this registry."""
        for name in registry.names():
            assert not name.startswith("ui_")
            assert not any(
                verb in name for verb in ("create", "delete", "update", "focus", "open_thesis")
            )

    def test_every_tool_has_a_positive_timeout(self, registry):
        for tool in registry.tools:
            assert tool.timeout_s > 0

    def test_quotes_timeout_clears_the_measured_endpoint_latency(self, registry):
        """/api/market/quotes measured ~18.5s on 2026-08-09 (uncached Yahoo
        fan-out per book). At the 10s default it could never return, so the
        model would learn nothing after a 10s wait, every time."""
        assert registry.get("get_live_quotes").timeout_s >= 15.0

    def test_quotes_timeout_stays_inside_the_loop_budget(self, registry):
        from llm.tool_loop import DEFAULT_LOOP_BUDGET_S
        for tool in registry.tools:
            assert tool.timeout_s < DEFAULT_LOOP_BUDGET_S / 2


# ── book id resolution ───────────────────────────────────────────────


class TestResolveBookId:
    def test_explicit_wins(self):
        room = SimpleNamespace(linked_book_id="iran-hormuz-graph", trading_config=None)
        assert resolve_book_id(room, "trump-tariffs-graph") == "trump-tariffs-graph"

    def test_falls_back_to_linked_book(self):
        room = SimpleNamespace(linked_book_id="iran-hormuz-graph", trading_config=None)
        assert resolve_book_id(room, None) == "iran-hormuz-graph"

    def test_falls_back_to_trading_config(self):
        room = SimpleNamespace(linked_book_id=None, trading_config={"bookId": "x-graph"})
        assert resolve_book_id(room) == "x-graph"

    def test_falls_back_to_snapshot_thesis_id(self):
        # v3 snapshots carry "thesisId", not book_id — the live contract.
        room = SimpleNamespace(
            linked_book_id=None, trading_config={"thesisId": "iran-hormuz-graph"}
        )
        assert resolve_book_id(room) == "iran-hormuz-graph"

    def test_room_model_preserves_linked_book_id(self):
        # Regression for the 2026-08-09 live bug: BaseModel silently dropped
        # linked_book_id from Room(**dict(select_star_row)).
        from datetime import datetime, timezone
        from uuid import uuid4

        from models import Room

        room = Room(
            **{
                "id": uuid4(),
                "created_at": datetime.now(timezone.utc),
                "token": "t",
                "linked_book_id": "iran-hormuz-graph",
            }
        )
        assert resolve_book_id(room) == "iran-hormuz-graph"

    def test_unbound_room_raises_with_actionable_message(self, room):
        with pytest.raises(ValueError, match="book_id"):
            resolve_book_id(room)


# ── payload hygiene ──────────────────────────────────────────────────


class TestShrink:
    def test_drops_trace_and_history_keys(self):
        payload = {"nodeStates": {"a": "fired"}, "horizonTrace": {"x": [1] * 500},
                   "priceHistory": [1] * 500}
        out = tools_mod._shrink(payload, 6000)
        assert "horizonTrace" not in out
        assert "priceHistory" not in out
        assert out["nodeStates"] == {"a": "fired"}
        assert "horizonTrace" in out["_truncated"]

    def test_caps_total_size_protecting_core_keys(self):
        payload = {
            "nodeStates": {"a": "fired"},
            "bulk": ["x" * 100 for _ in range(200)],
        }
        out = tools_mod._shrink(payload, 500, core=frozenset({"nodeStates"}))
        kept = {k: v for k, v in out.items() if k != "_truncated"}
        assert len(tools_mod.json.dumps(kept)) <= 500
        assert out["nodeStates"] == {"a": "fired"}
        assert "bulk" not in out

    def test_leaves_small_payloads_untouched(self):
        payload = {"a": 1, "b": "two"}
        assert tools_mod._shrink(payload, 6000) == payload

    def test_serialize_tool_result_hard_caps(self):
        text = tools_mod.serialize_tool_result({"blob": "y" * 20000}, limit=200)
        assert len(text) < 260
        assert "truncated at 200 characters" in text


# ── dialectic-internal executors ─────────────────────────────────────


class TestSearchTranscript:
    @pytest.mark.asyncio
    async def test_returns_chronological_attributed_rows(self, room):
        newest = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        oldest = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        db = FakeDB([
            {"content": "brent later", "speaker_type": "human",
             "created_at": newest, "display_name": "Dan"},
            {"content": "brent earlier", "speaker_type": "human",
             "created_at": oldest, "display_name": "Amo"},
        ])
        tool = build_registry(room, db).get("search_transcript")
        out = await tool.execute({"query": "brent"})

        assert out["count"] == 2
        assert [m["content"] for m in out["messages"]] == ["brent earlier", "brent later"]
        assert out["messages"][0]["said_by"] == "Amo"

    @pytest.mark.asyncio
    async def test_query_is_room_scoped_and_capped(self, room):
        db = FakeDB([])
        tool = build_registry(room, db).get("search_transcript")
        await tool.execute({"query": "brent", "limit": 99, "speaker": "Dan"})

        sql, args = db.queries[0]
        assert "t.room_id = $1" in sql
        assert "ILIKE" in sql
        assert args[0] == room.id
        assert args[1] == "%brent%"
        assert args[2] == "%Dan%"
        assert args[3] == 10  # clamped from 99

    @pytest.mark.asyncio
    async def test_empty_result_tells_the_model_not_to_invent(self, room):
        tool = build_registry(room, FakeDB([])).get("search_transcript")
        out = await tool.execute({"query": "nothing"})
        assert out["count"] == 0
        assert "do not assert" in out["note"]

    @pytest.mark.asyncio
    async def test_blank_query_rejected(self, room):
        tool = build_registry(room, FakeDB([])).get("search_transcript")
        with pytest.raises(ValueError):
            await tool.execute({"query": "   "})


class TestSearchMemories:
    @pytest.mark.asyncio
    async def test_results_carry_speaker_and_date(self, room, monkeypatch):
        memory_id = uuid4()
        match = SimilarityMatch(
            memory_id=memory_id, key="brent-level", content="Brent floor is 78",
            score=0.9, scope="room", owner_user_id=None, similarity=0.9,
            speaker_user_id=uuid4(), lanes="dense+fts",
        )

        async def fake_search(self, room_id, query, limit=10, min_score=0.5):
            assert room_id == room.id
            assert limit == 3
            return [match]

        from memory.manager import MemoryManager
        monkeypatch.setattr(MemoryManager, "search_memories", fake_search)

        db = FakeDB([{"id": memory_id,
                      "created_at": datetime(2026, 6, 14, tzinfo=timezone.utc),
                      "display_name": "Dan"}])
        tool = build_registry(room, db).get("search_memories")
        out = await tool.execute({"query": "brent floor", "limit": 3})

        assert out["count"] == 1
        assert out["memories"][0]["said_by"] == "Dan"
        assert out["memories"][0]["recorded"] == "2026-06-14"
        assert out["memories"][0]["content"] == "Brent floor is 78"

    @pytest.mark.asyncio
    async def test_attribution_failure_degrades_not_dies(self, room, monkeypatch):
        match = SimilarityMatch(
            memory_id=uuid4(), key="k", content="c", score=0.9, scope="room",
            owner_user_id=None, similarity=0.9, speaker_user_id=None, lanes="dense",
        )

        async def fake_search(self, room_id, query, limit=10, min_score=0.5):
            return [match]

        class ExplodingDB(FakeDB):
            async def fetch(self, query, *args):
                raise RuntimeError("attribution table gone")

        from memory.manager import MemoryManager
        monkeypatch.setattr(MemoryManager, "search_memories", fake_search)

        tool = build_registry(room, ExplodingDB()).get("search_memories")
        out = await tool.execute({"query": "anything"})
        assert out["count"] == 1
        assert out["memories"][0]["said_by"] == "unattributed"

    @pytest.mark.asyncio
    async def test_limit_is_clamped_to_ten(self, room, monkeypatch):
        seen = {}

        async def fake_search(self, room_id, query, limit=10, min_score=0.5):
            seen["limit"] = limit
            return []

        from memory.manager import MemoryManager
        monkeypatch.setattr(MemoryManager, "search_memories", fake_search)

        tool = build_registry(room, FakeDB([])).get("search_memories")
        await tool.execute({"query": "q", "limit": 50})
        assert seen["limit"] == 10


# ── the prediction draft (a proposal, never a write) ─────────


class TestDraftPredictionTool:
    """draft_prediction validates and shapes a proposal and writes NOTHING —
    the Accept tap in api/prediction_relay.py is the only write path."""

    DRAFT = {"statement": "Brent closes above $90 by end of Q3",
             "confidence": 0.7, "deadline": "2026-09-30"}

    @pytest.mark.asyncio
    async def test_returns_proposal_with_prediction_draft_provenance(self, room):
        tool = build_registry(room, FakeDB()).get("draft_prediction")
        out = await tool.execute({**self.DRAFT, "linked_book_id": " iran-hormuz-graph "})

        assert out["provenance"] == {"kind": "prediction_draft"}
        assert out["proposal"] == {
            "statement": "Brent closes above $90 by end of Q3",
            "confidence": 0.7,
            "deadline": "2026-09-30",
            "linked_book_id": "iran-hormuz-graph",
        }

    @pytest.mark.asyncio
    async def test_linked_book_id_is_optional(self, room):
        tool = build_registry(room, FakeDB()).get("draft_prediction")
        out = await tool.execute(self.DRAFT)
        assert "linked_book_id" not in out["proposal"]

    @pytest.mark.asyncio
    async def test_makes_no_network_call_and_no_db_write(self, room, td_env):
        """The write-guard test above checks names; this one checks behaviour —
        a draft must not touch tradingDesk OR the database."""
        requests = []

        def handler(request):
            requests.append(request)
            return json_response({})

        class RecordingDB(FakeDB):
            async def execute(self, *args):
                raise AssertionError("draft_prediction wrote to the database")

        install_transport(handler)
        tool = build_registry(room, RecordingDB()).get("draft_prediction")
        await tool.execute(self.DRAFT)
        assert requests == []

    @pytest.mark.asyncio
    async def test_blank_statement_rejected(self, room):
        tool = build_registry(room, FakeDB()).get("draft_prediction")
        with pytest.raises(ValueError, match="statement"):
            await tool.execute({**self.DRAFT, "statement": "   "})

    @pytest.mark.asyncio
    async def test_confidence_out_of_range_rejected(self, room):
        tool = build_registry(room, FakeDB()).get("draft_prediction")
        with pytest.raises(ValueError, match="confidence"):
            await tool.execute({**self.DRAFT, "confidence": 1.4})
        with pytest.raises(ValueError, match="confidence"):
            await tool.execute({**self.DRAFT, "confidence": "high"})

    @pytest.mark.asyncio
    async def test_non_iso_deadline_rejected(self, room):
        tool = build_registry(room, FakeDB()).get("draft_prediction")
        with pytest.raises(ValueError, match="deadline"):
            await tool.execute({**self.DRAFT, "deadline": "end of Q3"})


# ── tradingDesk-backed executors ─────────────────────────────────────


@pytest.fixture
def td_env(monkeypatch):
    monkeypatch.setenv("TRADINGDESK_URL", "http://td.test")
    monkeypatch.setenv("TRADINGDESK_USER", "dialectic")
    monkeypatch.setenv("TRADINGDESK_PASSWORD", "secret")
    td.reset()
    yield
    td.reset()


def install_transport(handler):
    """Point the module-level client at a MockTransport."""
    td._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def json_response(payload, status=200, content_type="application/json"):
    return httpx.Response(status, json=payload, headers={"content-type": content_type})


class TestTradingTools:
    @pytest.mark.asyncio
    async def test_quotes_filter_client_side(self, room, td_env):
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response([
                {"symbol": "XOP", "price": 41.2},
                {"symbol": "XLE", "price": 88.0},
            ])

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({"symbols": ["xop", "NOPE"]})

        assert out["count"] == 1
        assert out["quotes"][0]["symbol"] == "XOP"
        assert out["not_watched"] == ["NOPE"]

    @pytest.mark.asyncio
    async def test_empty_feed_warns_against_remembered_prices(self, room, td_env):
        """Unbound room: no snapshot to fall back to, so the answer is 'I could
        not check' — never a price the model reached for from memory."""
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response([])

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({})
        assert out["count"] == 0
        assert "snapshot_prices" not in out
        assert "remembered price" in out["note"]

    @pytest.mark.asyncio
    async def test_empty_feed_falls_back_to_snapshot_with_as_of(self, td_env):
        """The live feed being empty must not leave the model with nothing —
        but the snapshot levels have to arrive labelled as snapshot levels."""
        room = SimpleNamespace(id=uuid4(), linked_book_id="iran-hormuz-graph",
                               trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            if request.url.path == "/api/market/quotes":
                return json_response([])
            return json_response({"command_id": "thesis.open", "ok": True, "result": {
                "timestamp": "2026-08-09T05:21:23Z",
                "marketSnapshot": {"XOP": 41.2, "XLE": 88.0},
            }})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({})

        assert out["snapshot_prices"] == {"XOP": 41.2, "XLE": 88.0}
        assert out["as_of"] == "2026-08-09T05:21:23Z"
        assert "NOT the live tick" in out["source"]
        assert "as of that time" in out["note"]

    @pytest.mark.asyncio
    async def test_snapshot_fallback_honours_the_symbol_filter(self, td_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            if request.url.path == "/api/market/quotes":
                return json_response([])
            return json_response({"command_id": "thesis.open", "ok": True, "result": {
                "timestamp": "t", "marketSnapshot": {"XOP": 41.2, "XLE": 88.0}}})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({"symbols": ["xop"]})
        assert out["snapshot_prices"] == {"XOP": 41.2}

    @pytest.mark.asyncio
    async def test_ticker_filter_missing_the_snapshot_keys_shows_everything(self, td_env):
        """LIVE SHAPE: marketSnapshot is keyed by market field (brent, dxy),
        not by ticker, so a ticker filter matches nothing. Returning {} under
        a note promising levels would be a payload that lies about itself."""
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            if request.url.path == "/api/market/quotes":
                return json_response([])
            return json_response({"command_id": "thesis.open", "ok": True, "result": {
                "timestamp": "t",
                "marketSnapshot": {"brent": 99.78, "dxy": 98.87}}})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({"symbols": ["XOP", "BZ=F"]})

        assert out["snapshot_prices"] == {"brent": 99.78, "dxy": 98.87}
        assert "matched nothing" in out["filter_note"]
        # Nothing was watched because the feed was empty — not because these
        # symbols are untracked.
        assert "not_watched" not in out

    @pytest.mark.asyncio
    async def test_empty_snapshot_does_not_promise_levels(self, td_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            if request.url.path == "/api/market/quotes":
                return json_response([])
            return json_response({"command_id": "thesis.open", "ok": True,
                                  "result": {"timestamp": "t", "marketSnapshot": {}}})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({})
        assert "snapshot_prices" not in out
        assert "remembered price" in out["note"]

    @pytest.mark.asyncio
    async def test_snapshot_fallback_never_masks_a_live_quote(self, td_env):
        """A non-empty live feed must not trigger the fallback at all."""
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)
        paths = []

        def handler(request):
            paths.append(request.url.path)
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response([{"symbol": "XOP", "price": 41.2}])

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({})
        assert out["source"] == "live feed"
        assert "snapshot_prices" not in out
        assert "/api/v1/commands/thesis.open" not in paths

    @pytest.mark.asyncio
    async def test_snapshot_fallback_failure_leaves_the_honest_note(self, td_env):
        """If the fallback itself fails, the answer is still 'could not check'."""
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            if request.url.path == "/api/market/quotes":
                return json_response([])
            return json_response({"detail": "down"}, status=500)

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_live_quotes")
        out = await tool.execute({})
        assert "snapshot_prices" not in out
        assert "remembered price" in out["note"]

    @pytest.mark.asyncio
    async def test_thesis_state_drops_trace_and_stamps_book(self, td_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="iran-hormuz-graph",
                               trading_config=None)
        captured = {}

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            captured["path"] = request.url.path
            captured["body"] = request.content.decode()
            return json_response({"command_id": "thesis.open", "ok": True, "result": {
                "nodeStates": {"hormuz": "fired"},
                "horizonTrace": {"steps": [{"n": i} for i in range(400)]},
            }})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_thesis_state")
        out = await tool.execute({})

        assert captured["path"] == "/api/v1/commands/thesis.open"
        assert "iran-hormuz-graph" in captured["body"]
        assert out["nodeStates"] == {"hormuz": "fired"}
        assert "horizonTrace" not in out
        assert out["book_id"] == "iran-hormuz-graph"

    @pytest.mark.asyncio
    async def test_evaluate_scenario_echoes_provenance(self, td_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="iran-hormuz-graph",
                               trading_config=None)

        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            assert request.url.path == (
                "/api/v1/theses/iran-hormuz-graph/scenarios/closed-may/evaluate"
            )
            assert request.url.params["against_revision"] == "29395"
            return json_response({"baseRevision": 29395, "scenarioId": "closed-may",
                                  "probability": 0.42, "changedNodes": {}})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("evaluate_scenario")
        out = await tool.execute({"scenario_id": "closed-may", "against_revision": 29395})

        assert out["provenance"]["base_revision"] == 29395
        assert out["provenance"]["against_revision"] == 29395
        assert out["provenance"]["hypothetical"] is True

    @pytest.mark.asyncio
    async def test_evaluate_scenario_requires_scenario_id(self, td_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)
        tool = build_registry(room, FakeDB()).get("evaluate_scenario")
        with pytest.raises(ValueError, match="scenario_id"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_open_trades_unwraps_command_envelope(self, room, td_env):
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response({"command_id": "outcomes.open_trades", "ok": True,
                                  "result": {"count": 1, "trades": [{"ticker": "XOP"}]}})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_open_trades")
        out = await tool.execute({})
        assert out == {"count": 1, "trades": [{"ticker": "XOP"}]}

    @pytest.mark.asyncio
    async def test_html_catchall_is_rejected_not_parsed(self, room, td_env):
        """A 200 + text/html is tradingDesk's SPA shell, not data."""
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return httpx.Response(200, text="<!doctype html><div id=root>",
                                  headers={"content-type": "text/html"})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_polymarket_odds")
        with pytest.raises(td.TradingDeskError, match="not JSON"):
            await tool.execute({})


class TestThesisNewsTool:
    """get_thesis_news rides the service-token bridge path, not the JWT one."""

    @pytest.fixture
    def svc_env(self, td_env, monkeypatch):
        monkeypatch.setenv("TD_SERVICE_TOKEN", "svc-token")
        yield

    @pytest.mark.asyncio
    async def test_returns_headlines_with_service_token(self, svc_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="iran-hormuz-graph",
                               trading_config=None)

        def handler(request):
            assert request.url.path == "/api/bridge/news/iran-hormuz-graph"
            assert request.headers["x-service-token"] == "svc-token"
            assert "authorization" not in request.headers
            return json_response({"articles": [
                {"title": "Tankers divert", "url": "https://ex.com/1",
                 "seendate": "20260809", "domain": "ex.com"},
            ]})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_thesis_news")
        out = await tool.execute({})

        assert out["count"] == 1
        assert out["articles"][0]["title"] == "Tankers divert"
        assert out["book_id"] == "iran-hormuz-graph"

    @pytest.mark.asyncio
    async def test_note_only_degradation_is_not_an_error(self, svc_env):
        """GDELT unavailable answers 200 with articles [] + note — the model
        must get that note, not a tool failure it will paper over."""
        room = SimpleNamespace(id=uuid4(), linked_book_id="b", trading_config=None)

        def handler(request):
            return json_response({"articles": [],
                                  "note": "gdelt unavailable: ConnectError"})

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_thesis_news")
        out = await tool.execute({})

        assert out["articles"] == []
        assert out["count"] == 0
        assert "gdelt unavailable" in out["note"]
        assert out["book_id"] == "b"

    @pytest.mark.asyncio
    async def test_unknown_book_raises(self, svc_env):
        room = SimpleNamespace(id=uuid4(), linked_book_id="ghost-book",
                               trading_config=None)

        def handler(request):
            return json_response({"detail": "No book for thesis"}, status=404)

        install_transport(handler)
        tool = build_registry(room, FakeDB()).get("get_thesis_news")
        with pytest.raises(td.TradingDeskError, match="404"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_unbound_room_is_named_not_called(self, room, svc_env):
        tool = build_registry(room, FakeDB()).get("get_thesis_news")
        with pytest.raises(ValueError, match="book_id"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_missing_service_token_is_named(self, room, td_env, monkeypatch):
        monkeypatch.delenv("TD_SERVICE_TOKEN", raising=False)
        install_transport(lambda request: json_response({}))
        tool = build_registry(room, FakeDB()).get("get_thesis_news")
        with pytest.raises(td.TradingDeskError, match="TD_SERVICE_TOKEN"):
            await tool.execute({"book_id": "b"})


# ── tradingDesk client ───────────────────────────────────────────────


class TestTradingDeskClient:
    @pytest.mark.asyncio
    async def test_logs_in_once_and_reuses_the_token(self, td_env):
        calls = {"login": 0, "data": 0}

        def handler(request):
            if request.url.path == "/api/auth/login":
                calls["login"] += 1
                body = request.content.decode()
                assert "dialectic" in body and "secret" in body
                return json_response({"access_token": "jwt-1"})
            calls["data"] += 1
            assert request.headers["authorization"] == "Bearer jwt-1"
            return json_response({"ok": True})

        install_transport(handler)
        await td.get("/api/market/quotes")
        await td.get("/api/market/quotes")
        assert calls == {"login": 1, "data": 2}

    @pytest.mark.asyncio
    async def test_relogins_exactly_once_on_401(self, td_env):
        calls = {"login": 0, "data": 0}

        def handler(request):
            if request.url.path == "/api/auth/login":
                calls["login"] += 1
                return json_response({"access_token": f"jwt-{calls['login']}"})
            calls["data"] += 1
            if request.headers["authorization"] == "Bearer jwt-1":
                return json_response({"detail": "expired"}, status=401)
            return json_response({"ok": True})

        install_transport(handler)
        assert await td.get("/api/market/quotes") == {"ok": True}
        assert calls == {"login": 2, "data": 2}

    @pytest.mark.asyncio
    async def test_second_401_raises_instead_of_looping(self, td_env):
        calls = {"login": 0, "data": 0}

        def handler(request):
            if request.url.path == "/api/auth/login":
                calls["login"] += 1
                return json_response({"access_token": "jwt"})
            calls["data"] += 1
            return json_response({"detail": "nope"}, status=401)

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="401"):
            await td.get("/api/market/quotes")
        assert calls == {"login": 2, "data": 2}

    @pytest.mark.asyncio
    async def test_timeout_maps_to_tradingdesk_error(self, td_env):
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            raise httpx.ReadTimeout("too slow", request=request)

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="timed out"):
            await td.get("/api/market/quotes")

    @pytest.mark.asyncio
    async def test_unreachable_maps_to_tradingdesk_error(self, td_env):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="unreachable"):
            await td.get("/api/market/quotes")

    @pytest.mark.asyncio
    async def test_non_200_raises(self, td_env):
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response({"detail": "boom"}, status=500)

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="HTTP 500"):
            await td.get("/api/market/quotes")

    @pytest.mark.asyncio
    async def test_missing_credentials_are_named(self, monkeypatch):
        monkeypatch.setenv("TRADINGDESK_URL", "http://td.test")
        monkeypatch.delenv("TRADINGDESK_USER", raising=False)
        monkeypatch.delenv("TRADINGDESK_PASSWORD", raising=False)
        td.reset()
        install_transport(lambda request: json_response({}))
        with pytest.raises(td.TradingDeskError, match="TRADINGDESK_USER"):
            await td.get("/api/market/quotes")
        td.reset()

    @pytest.mark.asyncio
    async def test_login_html_response_is_rejected(self, td_env):
        def handler(request):
            return httpx.Response(200, text="<html>login page</html>",
                                  headers={"content-type": "text/html"})

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="not JSON"):
            await td.get("/api/market/quotes")

    @pytest.mark.asyncio
    async def test_run_command_rejects_non_object_result(self, td_env):
        def handler(request):
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response([1, 2, 3])

        install_transport(handler)
        with pytest.raises(td.TradingDeskError, match="expected an object"):
            await td.run_command("thesis.open", {"book_id": "b"})

    @pytest.mark.asyncio
    async def test_url_comes_from_env_at_call_time(self, td_env, monkeypatch):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            if request.url.path == "/api/auth/login":
                return json_response({"access_token": "jwt"})
            return json_response({"ok": True})

        install_transport(handler)
        monkeypatch.setenv("TRADINGDESK_URL", "http://elsewhere.test/")
        await td.get("/api/market/quotes")
        assert all(u.startswith("http://elsewhere.test/") for u in seen)


class TestToolRegistryConstruction:
    def test_registry_holds_arbitrary_tools(self):
        async def noop(args):
            return {}

        tool = Tool(name="t", description="d", input_schema={"type": "object", "properties": {}},
                    execute=noop, label="doing a thing")
        reg = ToolRegistry(tools=[tool])
        assert reg.get("t") is tool
        assert reg.labels() == {"t": "doing a thing"}
        assert reg.schemas() == [{"name": "t", "description": "d",
                                  "input_schema": {"type": "object", "properties": {}}}]


# ── propose_thesis — the conversation-born thesis proposal ───────────


class TestProposeThesis:
    """Proposal-only, same shape as draft_prediction: validate, hoist,
    never write. The one extra rule is one-thesis-per-room — the executor
    refuses in a bound room so the model explains instead of proposing."""

    def _tool(self, linked_book_id=None, is_home=False):
        from types import SimpleNamespace
        room = SimpleNamespace(id="room-1", linked_book_id=linked_book_id,
                               trading_config=None, is_home=is_home)
        return build_registry(room, FakeDB()).get("propose_thesis")

    @pytest.mark.asyncio
    async def test_refuses_in_home(self):
        """Home connects the schemes; durable theses belong in their rooms."""
        tool = self._tool(is_home=True)
        with pytest.raises(ValueError, match="Propose it in the scheme's room."):
            await tool.execute({"title": "T", "claim": "C"})

    @pytest.mark.asyncio
    async def test_shapes_a_proposal_with_provenance(self):
        out = await self._tool().execute({
            "title": "Sovereign Debt Doom Loop",
            "claim": "JGB auction failure forces BOJ retreat",
            "monthly_budget": 3000,
        })
        assert out["provenance"] == {"kind": "thesis_proposal"}
        assert out["proposal"] == {
            "title": "Sovereign Debt Doom Loop",
            "claim": "JGB auction failure forces BOJ retreat",
            "monthly_budget": 3000,
        }

    @pytest.mark.asyncio
    async def test_budget_defaults_when_omitted(self):
        out = await self._tool().execute({"title": "T", "claim": "C"})
        assert out["proposal"]["monthly_budget"] == 5000

    @pytest.mark.asyncio
    async def test_refuses_in_a_bound_room(self):
        tool = self._tool(linked_book_id="iran-hormuz-graph")
        with pytest.raises(ValueError, match="iran-hormuz-graph"):
            await tool.execute({"title": "T", "claim": "C"})

    @pytest.mark.asyncio
    async def test_requires_title_and_claim(self):
        with pytest.raises(ValueError, match="title"):
            await self._tool().execute({"claim": "C"})
        with pytest.raises(ValueError, match="claim"):
            await self._tool().execute({"title": "T"})

    @pytest.mark.asyncio
    async def test_bounds_the_budget(self):
        with pytest.raises(ValueError, match="monthly_budget"):
            await self._tool().execute(
                {"title": "T", "claim": "C", "monthly_budget": -1}
            )
        with pytest.raises(ValueError, match="monthly_budget"):
            await self._tool().execute(
                {"title": "T", "claim": "C", "monthly_budget": "lots"}
            )


class TestThesisProposalHoist:
    """The orchestrator scan that lifts the proposal to metadata."""

    def test_hoists_the_first_ok_thesis_proposal(self):
        from llm.orchestrator import _hoisted_thesis_proposal
        trace = [
            {"ok": True, "provenance": {"kind": "prediction_draft"},
             "input": {"statement": "not this one"}},
            {"ok": False, "provenance": {"kind": "thesis_proposal"},
             "input": {"title": "failed — skipped"}},
            {"ok": True, "provenance": {"kind": "thesis_proposal"},
             "input": {"title": "T", "claim": "C", "monthly_budget": 5000}},
        ]
        assert _hoisted_thesis_proposal(trace) == {
            "title": "T", "claim": "C", "monthly_budget": 5000,
        }

    def test_no_proposal_is_none(self):
        from llm.orchestrator import _hoisted_thesis_proposal
        assert _hoisted_thesis_proposal([]) is None
        assert _hoisted_thesis_proposal(
            [{"ok": True, "provenance": {"kind": "prediction_draft"},
              "input": {}}]
        ) is None


# ── read_article (defuddle sidecar) ──────────────────────────────────


@pytest.fixture
def defuddle_env(monkeypatch):
    monkeypatch.setenv("DEFUDDLE_URL", "http://defuddle.test")
    dc.reset()
    yield
    dc.reset()


def install_dc_transport(handler):
    """Point the defuddle client's module-level client at a MockTransport."""
    dc._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


ARTICLE = {
    "title": "Tankers divert",
    "author": "A. Reporter",
    "description": "Shipping lanes shift.",
    "site": "Example News",
    "published": "2026-08-10T09:00:00+00:00",
    "word_count": 900,
    "url": "https://ex.com/1",
    "content": "The straits narrowed overnight and the tankers turned.",
}


class TestReadArticleTool:
    @pytest.mark.asyncio
    async def test_returns_shaped_article(self, room, defuddle_env):
        def handler(request):
            assert request.url.path == "/extract"
            body = json.loads(request.content)
            assert body == {"url": "https://ex.com/1"}
            return json_response(ARTICLE)

        install_dc_transport(handler)
        registry = build_registry(room, FakeDB())
        tool = registry.get("read_article")
        assert tool is not None
        assert registry.labels()["read_article"] == "reading the article"

        out = await tool.execute({"url": "https://ex.com/1"})
        assert out["title"] == "Tankers divert"
        assert out["author"] == "A. Reporter"
        assert out["published"] == "2026-08-10T09:00:00+00:00"
        assert out["word_count"] == 900
        assert out["content"].startswith("The straits narrowed")
        assert "content_note" not in out

    @pytest.mark.asyncio
    async def test_long_content_is_cut_with_a_named_boundary(self, room, defuddle_env):
        def handler(request):
            return json_response({**ARTICLE,
                                  "content": "x" * (tools_mod.ARTICLE_CONTENT_CAP + 500)})

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("read_article")
        out = await tool.execute({"url": "https://ex.com/1"})

        assert len(out["content"]) == tools_mod.ARTICLE_CONTENT_CAP
        assert "cut at" in out["content_note"]
        assert "900-word" in out["content_note"]

    @pytest.mark.asyncio
    async def test_sidecar_down_raises_for_the_loop(self, room, defuddle_env):
        """Unreachable sidecar must surface as DefuddleError — the tool loop
        turns it into an is_error result; the executor never invents a body."""
        def handler(request):
            raise httpx.ConnectError("connection refused")

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("read_article")
        with pytest.raises(dc.DefuddleError, match="unreachable"):
            await tool.execute({"url": "https://ex.com/1"})

    @pytest.mark.asyncio
    async def test_upstream_refusal_names_the_reason(self, room, defuddle_env):
        def handler(request):
            return json_response({"error": "upstream returned HTTP 403"}, status=502)

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("read_article")
        with pytest.raises(dc.DefuddleError, match="502.*403"):
            await tool.execute({"url": "https://ex.com/paywalled"})

    @pytest.mark.asyncio
    async def test_url_arg_is_validated_before_any_fetch(self, room, defuddle_env):
        install_dc_transport(lambda request: json_response(ARTICLE))
        tool = build_registry(room, FakeDB()).get("read_article")
        with pytest.raises(ValueError, match="url is required"):
            await tool.execute({})
        with pytest.raises(ValueError, match="http"):
            await tool.execute({"url": "ftp://ex.com/1"})

    @pytest.mark.asyncio
    async def test_empty_content_says_so(self, room, defuddle_env):
        def handler(request):
            return json_response({**ARTICLE, "content": ""})

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("read_article")
        out = await tool.execute({"url": "https://ex.com/1"})
        assert out["content"] == ""
        assert "no article body" in out["note"]


# ── reading library tools (Phase 1) ──────────────────────────────────


class TestSaveReadingTool:
    """save_reading is a proposal: it validates and shapes, and writes
    NOTHING — the Accept tap in api/reading_relay.py is the only write."""

    @pytest.mark.asyncio
    async def test_proposal_carries_refetched_metadata(self, room, defuddle_env):
        def handler(request):
            body = json.loads(request.content)
            assert body == {"url": "https://ex.com/1"}
            return json_response(ARTICLE)

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("save_reading")
        out = await tool.execute({
            "url": "https://ex.com/1",
            "summary": "Tanker diversions tightened the straits premium.",
            "key_claims": ["Rates doubled", "Insurers withdrew"],
        })

        assert out["provenance"] == {"kind": "reading_draft"}
        proposal = out["proposal"]
        assert proposal["url"] == "https://ex.com/1"
        assert proposal["title"] == "Tankers divert"
        assert proposal["site"] == "Example News"
        assert proposal["summary"].startswith("Tanker diversions")
        assert proposal["key_claims"] == ["Rates doubled", "Insurers withdrew"]
        # The body never rides the proposal — the accept re-fetches it.
        assert "content" not in proposal

    @pytest.mark.asyncio
    async def test_unreadable_url_is_rejected_not_filed(self, room, defuddle_env):
        """A hallucinated article must fail here, not land in recall."""
        def handler(request):
            return json_response({**ARTICLE, "content": ""})

        install_dc_transport(handler)
        tool = build_registry(room, FakeDB()).get("save_reading")
        with pytest.raises(ValueError, match="readable article"):
            await tool.execute({"url": "https://ex.com/1", "summary": "s"})

    @pytest.mark.asyncio
    async def test_args_are_validated(self, room, defuddle_env):
        install_dc_transport(lambda request: json_response(ARTICLE))
        tool = build_registry(room, FakeDB()).get("save_reading")
        with pytest.raises(ValueError, match="url is required"):
            await tool.execute({"summary": "s"})
        with pytest.raises(ValueError, match="http"):
            await tool.execute({"url": "ftp://ex.com/1", "summary": "s"})
        with pytest.raises(ValueError, match="summary is required"):
            await tool.execute({"url": "https://ex.com/1"})
        with pytest.raises(ValueError, match="1000 characters"):
            await tool.execute({"url": "https://ex.com/1", "summary": "x" * 1001})


class TestSearchReadingTool:
    @pytest.mark.asyncio
    async def test_returns_ranked_extracts(self, room, monkeypatch):
        from llm import reading as reading_mod

        seen = {}

        async def fake_search(db, room_id, query, limit):
            seen.update(room_id=room_id, query=query, limit=limit)
            return [{
                "url": "https://ex.com/1", "title": "Tankers divert",
                "author": None, "site": "Example News",
                "published": "2026-08-10", "summary": "The straits narrowed.",
                "snippet": "the <b>tankers</b> turned", "saved_via": "proposal",
                "saved_at": "2026-08-11T05:30:00+00:00",
            }]

        monkeypatch.setattr(reading_mod, "search_reading", fake_search)
        tool = build_registry(room, FakeDB()).get("search_reading")
        out = await tool.execute({"query": "tankers"})

        assert seen == {"room_id": room.id, "query": "tankers", "limit": 5}
        assert out["count"] == 1
        assert out["readings"][0]["snippet"].startswith("the <b>tankers</b>")
        assert "note" not in out

    @pytest.mark.asyncio
    async def test_empty_result_says_so(self, room, monkeypatch):
        from llm import reading as reading_mod

        async def fake_search(db, room_id, query, limit):
            return []

        monkeypatch.setattr(reading_mod, "search_reading", fake_search)
        tool = build_registry(room, FakeDB()).get("search_reading")
        out = await tool.execute({"query": "nothing"})
        assert out["count"] == 0
        assert "never filed" in out["note"]

    @pytest.mark.asyncio
    async def test_query_is_required(self, room):
        tool = build_registry(room, FakeDB()).get("search_reading")
        with pytest.raises(ValueError, match="query is required"):
            await tool.execute({})


class TestReadingProposalHoist:
    """The orchestrator scan that lifts the draft to metadata.reading_proposal."""

    def test_hoists_the_first_ok_reading_draft(self):
        from llm.orchestrator import _hoisted_reading_proposal
        trace = [
            {"ok": True, "provenance": {"kind": "prediction_draft"},
             "input": {"statement": "not this one"}},
            {"ok": False, "provenance": {"kind": "reading_draft"},
             "input": {"url": "failed — skipped"}},
            {"ok": True, "provenance": {"kind": "reading_draft"},
             "input": {"url": "https://ex.com/1", "summary": "s"}},
        ]
        assert _hoisted_reading_proposal(trace) == {
            "url": "https://ex.com/1", "summary": "s", "accepted": False,
        }

    def test_no_proposal_is_none(self):
        from llm.orchestrator import _hoisted_reading_proposal
        assert _hoisted_reading_proposal([]) is None
        assert _hoisted_reading_proposal(
            [{"ok": True, "provenance": {"kind": "thesis_proposal"},
              "input": {}}]
        ) is None


# ── cairn dev-memory tools ───────────────────────────────────────────


@pytest.fixture
def cairn_env(monkeypatch):
    monkeypatch.setenv("CAIRN_URL", "http://cairn.test")
    cn.reset()
    yield
    cn.reset()


def install_cn_transport(handler):
    """Point the cairn client's module-level client at a MockTransport."""
    cn._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


CAIRN_SESSION = {
    "id": "session_abc123def456",
    "name": "auto: cairn 2026-08-13 22:41",
    "project": "cairn",
    "status": "completed",
    "started_at": "2026-08-13T22:41:12",
    "ended_at": "2026-08-13T22:42:45",
    "event_count": 9,
}


class TestCairnToolsFlag:
    def test_default_on(self, room, db, monkeypatch):
        monkeypatch.delenv("CAIRN_TOOLS_ENABLED", raising=False)
        registry = build_registry(room, db)
        assert "search_dev_sessions" in registry.names()

    def test_off_values_remove_the_group(self, room, db, monkeypatch):
        monkeypatch.delenv("CAIRN_TOOLS_ENABLED", raising=False)
        for off in ("0", "false", "no", "off"):
            monkeypatch.setenv("CAIRN_TOOLS_ENABLED", off)
            registry = build_registry(room, db)
            assert "search_dev_sessions" not in registry.names()
            assert "get_dev_session" not in registry.names()
            # The rest of the registry is untouched
            assert "get_live_quotes" in registry.names()

    def test_explicit_on_keeps_the_group(self, room, db, monkeypatch):
        monkeypatch.setenv("CAIRN_TOOLS_ENABLED", "1")
        registry = build_registry(room, db)
        assert "search_dev_insights" in registry.names()


class TestCairnTools:
    @pytest.mark.asyncio
    async def test_search_returns_shaped_sessions(self, registry, cairn_env):
        def handler(request):
            assert request.url.path == "/api/search/sessions"
            body = json.loads(request.content)
            assert body["query"] == "search indexes"
            return json_response(
                {"query": "search indexes", "count": 1, "results": [CAIRN_SESSION]}
            )

        install_cn_transport(handler)
        out = await registry.get("search_dev_sessions").execute(
            {"query": "search indexes"}
        )
        assert out["count"] == 1
        assert out["sessions"][0]["id"] == "session_abc123def456"
        assert "note" not in out

    @pytest.mark.asyncio
    async def test_empty_results_carry_the_honesty_note(self, registry, cairn_env):
        install_cn_transport(
            lambda request: json_response({"query": "x", "count": 0, "results": []})
        )
        out = await registry.get("search_dev_sessions").execute({"query": "x"})
        assert "Nothing in dev memory" in out["note"]

    @pytest.mark.asyncio
    async def test_query_is_validated_before_any_fetch(self, registry, cairn_env):
        called = []

        def handler(request):
            called.append(request)
            return json_response({})

        install_cn_transport(handler)
        with pytest.raises(ValueError):
            await registry.get("search_dev_sessions").execute({"query": "  "})
        assert called == []

    @pytest.mark.asyncio
    async def test_recent_activity_lists_sessions(self, registry, cairn_env):
        def handler(request):
            assert request.url.path == "/api/sessions"
            assert request.url.params.get("project") == "cairn"
            return json_response([CAIRN_SESSION])

        install_cn_transport(handler)
        out = await registry.get("recent_dev_activity").execute({"project": "cairn"})
        assert out["count"] == 1
        assert out["project"] == "cairn"

    @pytest.mark.asyncio
    async def test_get_session_joins_events(self, registry, cairn_env):
        def handler(request):
            if request.url.path == "/api/sessions/session_abc123def456":
                return json_response(CAIRN_SESSION)
            if request.url.path == "/api/sessions/session_abc123def456/events":
                return json_response([{"type": "commit", "message": "Git commit"}])
            raise AssertionError(f"unexpected path {request.url.path}")

        install_cn_transport(handler)
        out = await registry.get("get_dev_session").execute(
            {"session_id": "session_abc123def456"}
        )
        assert out["session"]["id"] == "session_abc123def456"
        assert out["event_count_shown"] == 1

    @pytest.mark.asyncio
    async def test_backend_down_raises_for_the_loop(self, registry, cairn_env):
        def handler(request):
            raise httpx.ConnectError("refused")

        install_cn_transport(handler)
        with pytest.raises(cn.CairnError, match="unreachable"):
            await registry.get("recent_dev_activity").execute({})

    @pytest.mark.asyncio
    async def test_html_200_is_refused(self, registry, cairn_env):
        install_cn_transport(
            lambda request: httpx.Response(
                200, text="<html>spa shell</html>",
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(cn.CairnError, match="not JSON"):
            await registry.get("recent_dev_activity").execute({})

    @pytest.mark.asyncio
    async def test_error_detail_is_surfaced(self, registry, cairn_env):
        install_cn_transport(
            lambda request: json_response({"detail": "Session not found"}, status=404)
        )
        with pytest.raises(cn.CairnError, match="Session not found"):
            await registry.get("get_dev_session").execute({"session_id": "session_x"})

    @pytest.mark.asyncio
    async def test_url_read_from_env_at_call_time(self, registry, cairn_env, monkeypatch):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return json_response([])

        install_cn_transport(handler)
        monkeypatch.setenv("CAIRN_URL", "http://late-bound.test")
        await registry.get("recent_dev_activity").execute({})
        assert seen and seen[0].startswith("http://late-bound.test")
