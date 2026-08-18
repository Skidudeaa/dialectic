"""
Contracts for the stakes → claims-ledger relay (api/stakes_relay.py plus the
hooks in stakes/manager.py).

The relay mirrors every commitment lifecycle event into tradingDesk's ONE
predictions ledger. The contracts that matter:

- it fires from the MANAGER, the write layer both doors share — the REST
  door (stakes/routes.py) and the WebSocket door (transport/handlers.py)
  both call these exact manager methods, so manager-level firing IS
  both-door coverage, plus one TestClient probe through the REST door;
- it is fire-and-forget: a down desk degrades to a debug log and the room
  write returns unchanged;
- idempotency keys are well-formed (`stake:{id}:created` /
  `:confidence:{seq}` / `:resolved`) and ride as td source_keys;
- a NULL creator maps to source_label "LLM" (the stakes convention);
- a commitment with no deadline or no stated confidence never touches the
  desk — inventing either is the confidence-75.0 poison.

Strategy matches tests/test_prediction_relay_endpoint.py — tradingDesk is
mocked at stakes_relay.td.post; no live Postgres, no live desk.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.stakes_relay as stakes_relay
import stakes.routes as stakes_routes
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.tradingdesk_client import TradingDeskError
from stakes.manager import CommitmentManager

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
COMMITMENT_ID = UUID("00000000-0000-0000-0000-0000000000cc")

DEADLINE = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

COMMITMENT = {
    "id": COMMITMENT_ID,
    "claim": "Brent closes above $90",
    "resolution_criteria": "ICE Brent front-month settle > 90",
    "category": "prediction",
    "deadline": DEADLINE,
}

EXPECTED_CREATE_BODY = {
    "statement": "Brent closes above $90 — resolves when: ICE Brent front-month settle > 90",
    "confidence": 0.7,
    "deadline": "2026-09-30",
    "tags": ["dialectic", "prediction"],
    "source_type": "dialectic_commitment",
    "source_label": "Amo",
    "source_ref": str(COMMITMENT_ID),
    "source_key": f"stake:{COMMITMENT_ID}:created",
}


# ── the relay coroutines themselves ──────────────────────────────────


@pytest.mark.asyncio
async def test_created_relays_the_mapped_body(monkeypatch):
    post = AsyncMock(return_value={"id": "td-1"})
    monkeypatch.setattr(stakes_relay.td, "post", post)

    task = stakes_relay.relay_created(
        dict(COMMITMENT), source_label="Amo", confidence=0.7,
    )
    await task

    post.assert_awaited_once_with(
        "/api/predictions", json_body=EXPECTED_CREATE_BODY,
    )


@pytest.mark.asyncio
async def test_no_deadline_never_touches_the_desk(monkeypatch):
    post = AsyncMock()
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_created(
        {**COMMITMENT, "deadline": None}, source_label="Amo", confidence=0.7,
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_confidence_never_touches_the_desk(monkeypatch):
    post = AsyncMock()
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_created(
        dict(COMMITMENT), source_label="Amo", confidence=None,
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_confidence_ensures_the_row_then_appends(monkeypatch):
    """The td prediction id is found by REPLAYING the idempotent create —
    the source_key is the durable lookup (module docstring), no cache."""
    post = AsyncMock(side_effect=[{"id": "td-1"}, {"ok": True}])
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_confidence(
        dict(COMMITMENT), source_label="Amo", seq=3,
        confidence=0.55, reasoning="tanker rates cooled",
    )

    assert post.await_count == 2
    ensure = post.await_args_list[0]
    assert ensure.args == ("/api/predictions",)
    assert ensure.kwargs["json_body"]["source_key"] == f"stake:{COMMITMENT_ID}:created"
    assert ensure.kwargs["json_body"]["confidence"] == 0.55
    append = post.await_args_list[1]
    assert append.args == (f"/api/predictions/td-1/confidence",)
    assert append.kwargs["json_body"] == {
        "confidence": 0.55,
        "reasoning": "tanker rates cooled",
        "source_key": f"stake:{COMMITMENT_ID}:confidence:3",
    }


@pytest.mark.asyncio
async def test_resolved_ensures_the_row_then_resolves(monkeypatch):
    post = AsyncMock(side_effect=[{"id": "td-1"}, {"ok": True}])
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_resolved(
        dict(COMMITMENT), source_label="Amo", resolution="correct",
        resolution_notes="settled at 93", last_confidence=0.7,
    )

    assert post.await_count == 2
    resolve = post.await_args_list[1]
    assert resolve.args == (f"/api/predictions/td-1/resolve",)
    assert resolve.kwargs["json_body"] == {
        "resolution": "correct",
        "resolution_notes": "settled at 93",
        "source_key": f"stake:{COMMITMENT_ID}:resolved",
    }


@pytest.mark.asyncio
async def test_resolve_without_any_confidence_stays_home(monkeypatch):
    """Nothing to score, nothing to ensure-create with — no HTTP at all."""
    post = AsyncMock()
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_resolved(
        dict(COMMITMENT), source_label="Amo", resolution="voided",
        resolution_notes=None, last_confidence=None,
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_desk_down_degrades_to_a_log_never_a_raise(monkeypatch):
    post = AsyncMock(side_effect=TradingDeskError("unreachable"))
    monkeypatch.setattr(stakes_relay.td, "post", post)

    # Awaiting the task must not raise — the caller never sees the desk.
    await stakes_relay.relay_created(
        dict(COMMITMENT), source_label="Amo", confidence=0.7,
    )
    await stakes_relay.relay_confidence(
        dict(COMMITMENT), source_label="Amo", seq=1, confidence=0.5,
    )
    await stakes_relay.relay_resolved(
        dict(COMMITMENT), source_label="Amo", resolution="correct",
        last_confidence=0.5,
    )


@pytest.mark.asyncio
async def test_unexpected_error_is_swallowed_too(monkeypatch):
    post = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(stakes_relay.td, "post", post)

    await stakes_relay.relay_created(
        dict(COMMITMENT), source_label="Amo", confidence=0.7,
    )


# ── the manager hooks (the layer both doors share) ───────────────────


def _manager_db(display_name="Amo", confidence_count=2, last_confidence=0.8,
                commitment_row=None):
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM users" in query:
            return {"display_name": display_name} if display_name else None
        if "COUNT(*)" in query:
            return {"n": confidence_count}
        if "SELECT confidence FROM commitment_confidence" in query:
            return {"confidence": last_confidence} if last_confidence is not None else None
        if "FROM commitments" in query:
            return commitment_row
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.execute = AsyncMock(return_value=None)
    return fake_db


@pytest.mark.asyncio
async def test_manager_create_fires_the_created_relay(monkeypatch):
    fired = MagicMock()
    monkeypatch.setattr(stakes_relay, "relay_created", fired)
    db = _manager_db()

    result = await CommitmentManager(db).create_commitment(
        room_id=ROOM_ID,
        claim="Brent closes above $90",
        resolution_criteria="ICE settle > 90",
        created_by_user_id=CALLER_ID,
        deadline=DEADLINE,
        initial_confidence=0.7,
    )

    assert result["status"] == "active"
    fired.assert_called_once()
    commitment = fired.call_args.args[0]
    assert commitment["claim"] == "Brent closes above $90"
    assert commitment["deadline"] == DEADLINE
    assert fired.call_args.kwargs == {"source_label": "Amo", "confidence": 0.7}


@pytest.mark.asyncio
async def test_manager_create_null_user_is_labeled_llm(monkeypatch):
    """The NULL-user convention: the LLM's own stakes group under 'LLM'."""
    fired = MagicMock()
    monkeypatch.setattr(stakes_relay, "relay_created", fired)
    db = _manager_db()

    await CommitmentManager(db).create_commitment(
        room_id=ROOM_ID,
        claim="c", resolution_criteria="r",
        created_by_user_id=None,
        deadline=DEADLINE,
        initial_confidence=0.6,
    )

    assert fired.call_args.kwargs["source_label"] == "LLM"


@pytest.mark.asyncio
async def test_manager_confidence_fires_with_the_table_derived_seq(monkeypatch):
    fired = MagicMock()
    monkeypatch.setattr(stakes_relay, "relay_confidence", fired)
    row = {
        "id": COMMITMENT_ID, "room_id": ROOM_ID, "thread_id": None,
        "status": "active", "claim": "c", "resolution_criteria": "r",
        "category": "prediction", "deadline": DEADLINE,
        "created_by_user_id": None,
    }
    db = _manager_db(confidence_count=3, commitment_row=row)

    await CommitmentManager(db).record_confidence(
        commitment_id=COMMITMENT_ID, user_id=CALLER_ID,
        confidence=0.55, reasoning="cooling",
    )

    fired.assert_called_once()
    assert fired.call_args.kwargs["seq"] == 3
    assert fired.call_args.kwargs["confidence"] == 0.55
    # The ensure-create is labeled by the commitment's CREATOR (NULL → LLM),
    # not by whoever restated confidence.
    assert fired.call_args.kwargs["source_label"] == "LLM"


@pytest.mark.asyncio
async def test_manager_resolve_fires_with_the_last_confidence(monkeypatch):
    fired = MagicMock()
    monkeypatch.setattr(stakes_relay, "relay_resolved", fired)
    row = {
        "id": COMMITMENT_ID, "room_id": ROOM_ID, "thread_id": None,
        "status": "active", "claim": "c", "resolution_criteria": "r",
        "category": "prediction", "deadline": DEADLINE,
        "created_by_user_id": CALLER_ID,
    }
    db = _manager_db(last_confidence=0.8, commitment_row=row)

    await CommitmentManager(db).resolve(
        commitment_id=COMMITMENT_ID, resolution="correct",
        resolved_by_user_id=CALLER_ID, resolution_notes="settled",
    )

    fired.assert_called_once()
    assert fired.call_args.kwargs["resolution"] == "correct"
    assert fired.call_args.kwargs["last_confidence"] == 0.8


@pytest.mark.asyncio
async def test_relay_scheduling_failure_never_breaks_the_write(monkeypatch):
    """The room write is the product; the mirror is chrome."""
    monkeypatch.setattr(
        stakes_relay, "relay_created", MagicMock(side_effect=RuntimeError("boom")),
    )
    db = _manager_db()

    result = await CommitmentManager(db).create_commitment(
        room_id=ROOM_ID, claim="c", resolution_criteria="r",
        created_by_user_id=CALLER_ID, deadline=DEADLINE,
        initial_confidence=0.7,
    )

    assert result["status"] == "active"


# ── the REST door (stakes/routes.py) reaches the same hook ───────────


def test_rest_door_create_fires_the_relay(monkeypatch):
    fired = MagicMock()
    monkeypatch.setattr(stakes_relay, "relay_created", fired)
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            return {"?column?": 1}
        if "FROM room_memberships" in query:
            return {"?column?": 1}
        if "FROM users" in query:
            return {"display_name": "Caller"}
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.execute = AsyncMock(return_value=None)

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[stakes_routes.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[stakes_routes.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )
    try:
        resp = TestClient(main_mod.app).post(
            f"/stakes/rooms/{ROOM_ID}/commitments",
            json={
                "claim": "Brent closes above $90",
                "resolution_criteria": "ICE settle > 90",
                "deadline": "2026-09-30T00:00:00Z",
                "initial_confidence": 0.7,
            },
        )
    finally:
        main_mod.app.dependency_overrides.clear()

    assert resp.status_code == 200
    fired.assert_called_once()
    assert fired.call_args.kwargs["confidence"] == 0.7
    assert fired.call_args.kwargs["source_label"] == "Caller"
