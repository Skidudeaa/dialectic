"""
Claude's Home context: the PromptBuilder layer and the orchestrator helper.

The builder inserts `## Shared Home Activity` between this-room shared
memory and personal cross-session memory whenever context is provided; the
orchestrator helper decides WHEN it is provided — Home rooms only, primary
turns only, last human speaker as viewer, 2-second budget, and an explicit
unavailable marker instead of a failed or stale digest.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

import llm.orchestrator as orch_mod
from llm.orchestrator import HOME_ACTIVITY_UNAVAILABLE, LLMOrchestrator
from llm.prompts import PromptBuilder
from models import Message, MessageType, Room, SpeakerType

NOW = datetime(2026, 8, 12, 5, 0, tzinfo=timezone.utc)
HUMAN = UUID("00000000-0000-0000-0000-000000000501")


def _room(is_home: bool = True) -> Room:
    return Room(created_at=NOW, token="prompt-fixture", name="Home",
                is_home=is_home)


def _msg(speaker_type: SpeakerType, user_id=None) -> Message:
    return Message(
        thread_id=uuid4(), sequence=1, created_at=NOW,
        speaker_type=speaker_type, user_id=user_id,
        message_type=MessageType.TEXT, content="hello",
    )


# ── PromptBuilder layer ──

def test_build_inserts_the_home_section() -> None:
    prompt = PromptBuilder().build(
        room=_room(), users=[], messages=[], memories=[],
        home_activity_context="HOME-CTX-SENTINEL",
    )
    assert "## Shared Home Activity" in prompt.system
    assert "HOME-CTX-SENTINEL" in prompt.system


def test_home_section_absent_without_context() -> None:
    prompt = PromptBuilder().build(
        room=_room(), users=[], messages=[], memories=[],
    )
    assert "Shared Home Activity" not in prompt.system


def test_home_section_sits_before_cross_session_memory() -> None:
    xsess = SimpleNamespace(
        total_injected=1, to_prompt_section=lambda: "XSESS-SENTINEL"
    )
    prompt = PromptBuilder().build(
        room=_room(), users=[], messages=[], memories=[],
        cross_session_context=xsess,
        home_activity_context="HOME-CTX-SENTINEL",
    )
    assert (
        prompt.system.index("HOME-CTX-SENTINEL")
        < prompt.system.index("XSESS-SENTINEL")
    )


# ── Orchestrator helper ──

def _orchestrator(db_pool=None) -> LLMOrchestrator:
    return LLMOrchestrator(SimpleNamespace(), db_pool=db_pool)


def _rendering_service(monkeypatch, rendered="RENDERED-HOME-DIGEST"):
    build = AsyncMock(return_value=SimpleNamespace(
        to_prompt_section=lambda: rendered
    ))
    monkeypatch.setattr(
        orch_mod, "HomeActivityService",
        lambda db: SimpleNamespace(build=build),
    )
    return build


@pytest.mark.asyncio
async def test_normal_rooms_get_no_home_context(monkeypatch) -> None:
    build = _rendering_service(monkeypatch)
    ctx = await _orchestrator()._get_home_activity_context(
        _room(is_home=False), [_msg(SpeakerType.HUMAN, HUMAN)], include=True
    )
    assert ctx is None
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_provoker_and_protocol_turns_are_excluded(monkeypatch) -> None:
    build = _rendering_service(monkeypatch)
    ctx = await _orchestrator()._get_home_activity_context(
        _room(), [_msg(SpeakerType.HUMAN, HUMAN)], include=False
    )
    assert ctx is None
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_human_message_yields_the_marker() -> None:
    ctx = await _orchestrator()._get_home_activity_context(
        _room(), [_msg(SpeakerType.LLM_PRIMARY)], include=True
    )
    assert ctx == HOME_ACTIVITY_UNAVAILABLE
    assert "do not claim this digest is current" in ctx


@pytest.mark.asyncio
async def test_renders_for_the_most_recent_human_viewer(monkeypatch) -> None:
    build = _rendering_service(monkeypatch)
    earlier, latest = uuid4(), uuid4()
    messages = [
        _msg(SpeakerType.HUMAN, earlier),
        _msg(SpeakerType.LLM_PRIMARY),
        _msg(SpeakerType.HUMAN, latest),
        _msg(SpeakerType.LLM_PRIMARY),
    ]
    ctx = await _orchestrator()._get_home_activity_context(
        _room(), messages, include=True
    )
    assert ctx == "RENDERED-HOME-DIGEST"
    build.assert_awaited_once_with(latest)


@pytest.mark.asyncio
async def test_projection_error_yields_the_marker(monkeypatch) -> None:
    monkeypatch.setattr(
        orch_mod, "HomeActivityService",
        lambda db: SimpleNamespace(
            build=AsyncMock(side_effect=RuntimeError("boom"))
        ),
    )
    ctx = await _orchestrator()._get_home_activity_context(
        _room(), [_msg(SpeakerType.HUMAN, HUMAN)], include=True
    )
    assert ctx == HOME_ACTIVITY_UNAVAILABLE


@pytest.mark.asyncio
async def test_slow_projection_times_out_without_cancelling_the_turn(
    monkeypatch,
) -> None:
    async def slow_build(viewer):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(orch_mod, "HOME_ACTIVITY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        orch_mod, "HomeActivityService",
        lambda db: SimpleNamespace(build=slow_build),
    )
    ctx = await _orchestrator()._get_home_activity_context(
        _room(), [_msg(SpeakerType.HUMAN, HUMAN)], include=True
    )
    # The helper absorbs the timeout — the Home conversation turn goes on.
    assert ctx == HOME_ACTIVITY_UNAVAILABLE


@pytest.mark.asyncio
async def test_projection_runs_on_a_fresh_pool_connection(monkeypatch) -> None:
    """Amendment 2026-08-12: with a pool available, the 2s-budgeted query
    runs on its own connection so a racy cancel never lands on the
    connection the rest of the turn is using."""
    acquired = SimpleNamespace()

    class FakeAcquire:
        async def __aenter__(self):
            return acquired

        async def __aexit__(self, *args):
            return False

    pool = SimpleNamespace(acquire=lambda: FakeAcquire())
    seen = {}

    def service(db):
        seen["db"] = db
        return SimpleNamespace(build=AsyncMock(return_value=SimpleNamespace(
            to_prompt_section=lambda: "OK"
        )))

    monkeypatch.setattr(orch_mod, "HomeActivityService", service)
    ctx = await _orchestrator(db_pool=pool)._get_home_activity_context(
        _room(), [_msg(SpeakerType.HUMAN, HUMAN)], include=True
    )
    assert ctx == "OK"
    assert seen["db"] is acquired
