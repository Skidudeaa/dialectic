"""
Tests for the inline Dialectic push: the v3 contract, the never-raise
guarantee, and the coordinator's push-or-stay-quiet decision.

WHY the never-raise tests matter most: this is the only outbound network
call inside a fetch cycle, and the cycle holds the per-thesis lock while it
runs. If a Dialectic outage could raise through push_snapshot, a third-party
service being down would stop the desk from fetching prices.
"""

import json
import time

import pytest

from web.persistence.repository import Repository
from web.runtime import dialectic_push
from web.runtime.coordinator import RuntimeCoordinator


V2_EXPORT = {
    "v": 2,
    "timestamp": "2026-08-09T05:07:15Z",
    "title": "Iran/Hormuz Thesis",
    "nodeStates": {"hormuz_closure": "fired", "brent_spike": "stable"},
    "confluenceScores": {"oil_supply_shock": 0.61},
    "cascadePhase": {"number": 2, "key": "escalation", "status": "active"},
    "feedFreshness": {"gdelt": "stale"},
    "thesisId": "iran-hormuz-graph",
    "revision": 4211,
    "generatedAt": "2026-08-09T05:07:15.775368+00:00",
}

EVENTS = [
    {
        "event_id": "e1",
        "thesis_id": "iran-hormuz-graph",
        "revision": 4211,
        "event_type": "node.state_changed",
        "severity": "critical",
        "node_id": "hormuz_closure",
        "old_value": "approaching",
        "new_value": "fired",
        "occurred_at": "2026-08-09T05:07:15+00:00",
        "dedupe_key": "iran-hormuz-graph:node.state_changed:hormuz_closure:4211",
    },
]


# =========================================================================
# v3 PAYLOAD
# =========================================================================


class TestBuildV3Payload:
    def test_stamps_version_three(self):
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, EVENTS)
        assert payload["v"] == 3

    def test_preserves_every_v2_field(self):
        """v3 is additive — a v2 consumer must see no field disappear."""
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, EVENTS)
        for key, value in V2_EXPORT.items():
            if key in ("v", "thesisId"):
                continue
            assert payload[key] == value

    def test_does_not_mutate_the_caller_snapshot(self):
        """The coordinator keeps `export` as its in-memory latest snapshot —
        stamping v=3 onto that object would corrupt the next diff."""
        original = json.loads(json.dumps(V2_EXPORT))
        dialectic_push.build_v3_payload("book", V2_EXPORT, EVENTS)
        assert V2_EXPORT == original

    def test_projects_events_to_the_wire_shape(self):
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, EVENTS)
        assert payload["alertEvents"] == [{
            "event_type": "node.state_changed",
            "severity": "critical",
            "node_id": "hormuz_closure",
            "old_value": "approaching",
            "new_value": "fired",
        }]

    def test_internal_event_identity_is_not_shipped(self):
        """event_id and dedupe_key are tradingDesk-internal."""
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, EVENTS)
        evt = payload["alertEvents"][0]
        assert "event_id" not in evt
        assert "dedupe_key" not in evt

    def test_no_events_gives_empty_list_not_null(self):
        """Dialectic distinguishes v3-with-no-events (curator stays quiet)
        from v1/v2-with-no-field (legacy curator behavior). None would read
        as the latter."""
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, [])
        assert payload["alertEvents"] == []
        payload = dialectic_push.build_v3_payload("book", V2_EXPORT, None)
        assert payload["alertEvents"] == []

    def test_thesis_id_comes_from_the_argument(self):
        payload = dialectic_push.build_v3_payload("other-book", V2_EXPORT, [])
        assert payload["thesisId"] == "other-book"

    def test_identity_fields_default_when_absent(self):
        bare = {"v": 2, "timestamp": "t", "nodeStates": {}}
        payload = dialectic_push.build_v3_payload("book", bare, [])
        assert payload["revision"] is None
        assert payload["generatedAt"] is None


# =========================================================================
# push_snapshot — the never-raise contract
# =========================================================================


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Stand-in for httpx.AsyncClient recording every POST."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []
        self.is_closed = False

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            return _FakeResponse(200)
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def spooled(monkeypatch):
    """Capture spool_to_outbox calls instead of writing files."""
    calls = []
    monkeypatch.setattr(
        dialectic_push, "_spool_sync",
        lambda room_id, payload, reason: calls.append((room_id, payload, reason)),
    )
    return calls


@pytest.fixture
def no_drain(monkeypatch):
    """Default: nothing queued in the file outbox."""
    monkeypatch.setattr(dialectic_push, "_drain_sync", lambda *a, **k: 0)


def _install_client(monkeypatch, client):
    monkeypatch.setattr(dialectic_push, "_get_client", lambda: client)
    return client


class TestPushSnapshot:
    @pytest.mark.asyncio
    async def test_success_returns_true_and_posts_v3(
        self, monkeypatch, spooled, no_drain,
    ):
        client = _install_client(monkeypatch, _FakeClient([_FakeResponse(200)]))
        ok = await dialectic_push.push_snapshot(
            "iran-hormuz-graph", V2_EXPORT, EVENTS,
            "room-1", "tok", "events",
        )
        assert ok is True
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["v"] == 3
        assert client.posts[0]["url"].endswith("/rooms/room-1/trading/snapshot")
        assert spooled == []

    @pytest.mark.asyncio
    async def test_sends_room_token_header(self, monkeypatch, spooled, no_drain):
        client = _install_client(monkeypatch, _FakeClient([_FakeResponse(200)]))
        await dialectic_push.push_snapshot(
            "b", V2_EXPORT, [], "room-1", "the-token", "heartbeat",
        )
        assert client.posts[0]["headers"]["X-Room-Token"] == "the-token"

    @pytest.mark.asyncio
    async def test_http_error_spools_and_returns_false(
        self, monkeypatch, spooled, no_drain,
    ):
        _install_client(monkeypatch, _FakeClient([_FakeResponse(500, "boom")]))
        ok = await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert ok is False
        assert len(spooled) == 1
        room_id, payload, reason = spooled[0]
        assert room_id == "room-1"
        assert payload["v"] == 3
        assert "events" in reason

    @pytest.mark.asyncio
    async def test_transport_exception_spools_and_returns_false(
        self, monkeypatch, spooled, no_drain,
    ):
        """A connection error must not escape — this is the outage case."""
        _install_client(
            monkeypatch, _FakeClient([ConnectionError("dialectic is down")]),
        )
        ok = await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert ok is False
        assert len(spooled) == 1

    @pytest.mark.asyncio
    async def test_spool_failure_still_returns_false_not_raise(
        self, monkeypatch, no_drain,
    ):
        """Belt AND braces: even the failure handler failing must not raise."""
        _install_client(monkeypatch, _FakeClient([ConnectionError("down")]))

        def _explode(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(dialectic_push, "_spool_sync", _explode)
        ok = await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_no_drain_attempted_when_push_failed(self, monkeypatch, spooled):
        """During an outage the drain must cost zero extra requests."""
        _install_client(monkeypatch, _FakeClient([ConnectionError("down")]))
        drained = []
        monkeypatch.setattr(
            dialectic_push, "_drain_sync",
            lambda *a, **k: drained.append(a) or 0,
        )
        await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert drained == []

    @pytest.mark.asyncio
    async def test_drain_runs_after_success(self, monkeypatch, spooled):
        _install_client(monkeypatch, _FakeClient([_FakeResponse(200)]))
        drained = []
        monkeypatch.setattr(
            dialectic_push, "_drain_sync",
            lambda url, room, tok, **k: drained.append(room) or 0,
        )
        await dialectic_push.push_snapshot(
            "b", V2_EXPORT, [], "room-1", "tok", "heartbeat",
        )
        assert drained == ["room-1"]

    @pytest.mark.asyncio
    async def test_current_revision_reposted_after_a_real_drain(
        self, monkeypatch, spooled,
    ):
        """Replayed spools are OLDER snapshots and Dialectic upserts
        thesis_state_current on every receipt — without the re-post the room
        would be left showing stale state."""
        client = _install_client(
            monkeypatch, _FakeClient([_FakeResponse(200), _FakeResponse(200)]),
        )
        monkeypatch.setattr(dialectic_push, "_drain_sync", lambda *a, **k: 3)
        ok = await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert ok is True
        assert len(client.posts) == 2
        assert client.posts[-1]["json"]["revision"] == 4211

    @pytest.mark.asyncio
    async def test_no_repost_when_nothing_was_drained(self, monkeypatch, spooled):
        client = _install_client(monkeypatch, _FakeClient([_FakeResponse(200)]))
        monkeypatch.setattr(dialectic_push, "_drain_sync", lambda *a, **k: 0)
        await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert len(client.posts) == 1

    @pytest.mark.asyncio
    async def test_drain_failure_does_not_flip_a_successful_push(
        self, monkeypatch, spooled,
    ):
        _install_client(monkeypatch, _FakeClient([_FakeResponse(200)]))

        def _explode(*a, **k):
            raise RuntimeError("outbox unreadable")

        monkeypatch.setattr(dialectic_push, "_drain_sync", _explode)
        ok = await dialectic_push.push_snapshot(
            "b", V2_EXPORT, EVENTS, "room-1", "tok", "events",
        )
        assert ok is True


# =========================================================================
# COORDINATOR GATING
# =========================================================================


@pytest.fixture
def coordinator():
    repo = Repository(":memory:")
    repo.initialize()
    return RuntimeCoordinator(repo=repo, ws_manager=None, tick_interval=300.0)


class TestPushDecision:
    def test_events_always_push(self, coordinator):
        coordinator._last_dialectic_push["b"] = time.monotonic()  # just pushed
        assert coordinator._should_push_dialectic("b", EVENTS) is True

    def test_first_cycle_pushes_even_without_events(self, coordinator):
        """Nothing recorded yet — bootstrap the room after a restart."""
        assert coordinator._should_push_dialectic("b", []) is True

    def test_quiet_cycle_inside_the_window_stays_quiet(self, coordinator):
        coordinator._last_dialectic_push["b"] = time.monotonic() - 60.0
        assert coordinator._should_push_dialectic("b", []) is False

    def test_quiet_cycle_past_the_window_heartbeats(self, coordinator):
        elapsed = RuntimeCoordinator.DIALECTIC_HEARTBEAT_SECONDS + 1.0
        coordinator._last_dialectic_push["b"] = time.monotonic() - elapsed
        assert coordinator._should_push_dialectic("b", []) is True


class TestMaybePushDialectic:
    @pytest.mark.asyncio
    async def test_book_without_a_room_is_skipped(self, coordinator, monkeypatch):
        called = []
        monkeypatch.setattr(
            dialectic_push, "push_snapshot",
            lambda **kw: called.append(kw),
        )
        await coordinator._maybe_push_dialectic(
            "b", {"meta": {}}, V2_EXPORT, EVENTS,
        )
        assert called == []

    @pytest.mark.asyncio
    async def test_book_with_room_but_no_token_is_skipped(
        self, coordinator, monkeypatch,
    ):
        """A half-configured book must not push an unauthenticated payload."""
        called = []
        monkeypatch.setattr(
            dialectic_push, "push_snapshot",
            lambda **kw: called.append(kw),
        )
        await coordinator._maybe_push_dialectic(
            "b", {"meta": {"dialecticRoomId": "r"}}, V2_EXPORT, EVENTS,
        )
        assert called == []

    @pytest.mark.asyncio
    async def test_successful_push_arms_the_heartbeat_clock(
        self, coordinator, monkeypatch,
    ):
        async def _ok(**kw):
            return True

        monkeypatch.setattr(dialectic_push, "push_snapshot", _ok)
        await coordinator._maybe_push_dialectic(
            "b", {"meta": {"dialecticRoomId": "r", "dialecticRoomToken": "t"}},
            V2_EXPORT, EVENTS,
        )
        assert "b" in coordinator._last_dialectic_push

    @pytest.mark.asyncio
    async def test_failed_push_leaves_the_heartbeat_due(
        self, coordinator, monkeypatch,
    ):
        """A spooled failure must retry next tick, not wait an hour."""
        async def _fail(**kw):
            return False

        monkeypatch.setattr(dialectic_push, "push_snapshot", _fail)
        await coordinator._maybe_push_dialectic(
            "b", {"meta": {"dialecticRoomId": "r", "dialecticRoomToken": "t"}},
            V2_EXPORT, EVENTS,
        )
        assert "b" not in coordinator._last_dialectic_push
        assert coordinator._should_push_dialectic("b", []) is True

    @pytest.mark.asyncio
    async def test_a_raising_pusher_cannot_break_the_cycle(
        self, coordinator, monkeypatch,
    ):
        """push_snapshot is written not to raise; this is the second belt."""
        async def _boom(**kw):
            raise RuntimeError("import blew up")

        monkeypatch.setattr(dialectic_push, "push_snapshot", _boom)
        await coordinator._maybe_push_dialectic(
            "b", {"meta": {"dialecticRoomId": "r", "dialecticRoomToken": "t"}},
            V2_EXPORT, EVENTS,
        )
        assert "b" not in coordinator._last_dialectic_push

    @pytest.mark.asyncio
    async def test_reason_tag_distinguishes_heartbeat_from_events(
        self, coordinator, monkeypatch,
    ):
        seen = {}

        async def _capture(**kw):
            seen.update(kw)
            return True

        monkeypatch.setattr(dialectic_push, "push_snapshot", _capture)
        meta = {"meta": {"dialecticRoomId": "r", "dialecticRoomToken": "t"}}

        await coordinator._maybe_push_dialectic("b", meta, V2_EXPORT, EVENTS)
        assert seen["reason"] == "events"

        coordinator._last_dialectic_push.clear()
        await coordinator._maybe_push_dialectic("b2", meta, V2_EXPORT, [])
        assert seen["reason"] == "heartbeat"
