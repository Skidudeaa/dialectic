"""
Tests for the command registry + ``/api/v1/commands`` HTTP surface.

WHY this file: the registry is the single contract between the palette and
LLM. These tests pin the full contract — registration uniqueness, schema
validity, dispatch behaviour, concurrent isolation.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.runtime import command_registry
from web.runtime.command_registry import Command, schema_from


SEED_IDS = {
    "thesis.open",
    "thesis.diff.last_hour",
    "market.watchlist",
    "outcomes.morning_brief",
    "outcomes.open_trades",
    "ui.focus_panel",
}


client = TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def restore_registry():
    """Reset the registry around each test to keep isolation.

    Some tests register temporary commands; the seed helper rewrites the
    canonical six so the session stays deterministic.
    """
    yield
    command_registry._seed_builtin_commands()


# ─── Registry-level tests ────────────────────────────────────────────────

class TestRegistryShape:
    def test_seeded_ids_present(self):
        assert SEED_IDS.issubset(set(command_registry.COMMANDS.keys()))

    def test_list_commands_returns_dicts(self):
        catalog = command_registry.list_commands()
        assert isinstance(catalog, list)
        assert len(catalog) >= len(SEED_IDS)
        for entry in catalog:
            assert {"id", "title", "description", "category", "input_schema"}.issubset(entry)

    def test_every_schema_is_valid_jsonschema(self):
        for cmd in command_registry.COMMANDS.values():
            # Raises on malformed schema.
            Draft202012Validator.check_schema(cmd.input_schema)

    def test_duplicate_registration_raises(self):
        existing = next(iter(command_registry.COMMANDS.values()))
        dup = Command(
            id=existing.id,
            title="x", description="x", category="test",
            input_schema={"type": "object"},
            handler=existing.handler,
        )
        with pytest.raises(ValueError):
            command_registry.register(dup)

    def test_get_returns_none_for_unknown(self):
        assert command_registry.get("does.not.exist") is None

    def test_schema_from_strips_title(self):
        class M(BaseModel):
            x: int = Field(..., description="an int")
        schema = schema_from(M)
        assert "title" not in schema
        assert "properties" in schema
        assert "x" in schema["properties"]


# ─── HTTP GET /api/v1/commands ───────────────────────────────────────────

class TestGetCommands:
    def test_requires_auth(self):
        resp = client.get("/api/v1/commands")
        assert resp.status_code in (401, 403)

    def test_lists_seeded_commands(self, auth_headers):
        resp = client.get("/api/v1/commands", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "commands" in body
        returned_ids = {c["id"] for c in body["commands"]}
        assert SEED_IDS.issubset(returned_ids)

    def test_every_returned_schema_validates(self, auth_headers):
        resp = client.get("/api/v1/commands", headers=auth_headers)
        body = resp.json()
        for cmd in body["commands"]:
            Draft202012Validator.check_schema(cmd["input_schema"])


# ─── HTTP POST /api/v1/commands/{id} ─────────────────────────────────────

class TestDispatch:
    def test_unknown_command_returns_404(self, auth_headers):
        resp = client.post(
            "/api/v1/commands/nonexistent.cmd",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 404

    def test_missing_required_field_returns_400(self, auth_headers):
        # thesis.open requires book_id
        resp = client.post(
            "/api/v1/commands/thesis.open",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "validation_errors" in body["detail"]

    def test_wrong_type_returns_400(self, auth_headers):
        resp = client.post(
            "/api/v1/commands/thesis.open",
            headers=auth_headers,
            json={"book_id": 42},  # int, schema requires string
        )
        assert resp.status_code == 400

    def test_invalid_enum_returns_400(self, auth_headers):
        # panel_name is a Literal[...] → enum validation
        resp = client.post(
            "/api/v1/commands/ui.focus_panel",
            headers=auth_headers,
            json={"panel_name": "not_a_real_panel"},
        )
        assert resp.status_code == 400

    def test_handler_dispatch_ok_empty_input(self, auth_headers):
        resp = client.post(
            "/api/v1/commands/outcomes.open_trades",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["command_id"] == "outcomes.open_trades"
        assert "trades" in body["result"]
        assert "count" in body["result"]

    def test_handler_receives_validated_args(self, auth_headers):
        """Register a test command whose handler echoes the kwargs it got."""

        class EchoInput(BaseModel):
            message: str

        captured: dict = {}

        async def _echo(args: dict):
            captured.update(args)
            return {"echoed": args}

        command_registry.register(Command(
            id="test.echo",
            title="Echo",
            description="Test command",
            category="test",
            input_schema=schema_from(EchoInput),
            handler=_echo,
        ))
        try:
            resp = client.post(
                "/api/v1/commands/test.echo",
                headers=auth_headers,
                json={"message": "hello"},
            )
            assert resp.status_code == 200
            assert captured == {"message": "hello"}
            assert resp.json()["result"] == {"echoed": {"message": "hello"}}
        finally:
            command_registry.COMMANDS.pop("test.echo", None)

    def test_handler_error_propagates_as_400_for_value_errors(self, auth_headers):
        # Nudge thesis.open with a plausibly-formatted but nonexistent book id.
        resp = client.post(
            "/api/v1/commands/thesis.open",
            headers=auth_headers,
            json={"book_id": "nonexistent-book"},
        )
        # Adapter raises FileNotFoundError -> mapped to 400
        assert resp.status_code == 400

    def test_invalid_book_id_shape_returns_400(self, auth_headers):
        # Adapter _validate_book_id rejects traversal-ish ids → ValueError → 400
        resp = client.post(
            "/api/v1/commands/thesis.open",
            headers=auth_headers,
            json={"book_id": "../etc/passwd"},
        )
        assert resp.status_code == 400

    def test_requires_auth(self):
        resp = client.post("/api/v1/commands/outcomes.open_trades", json={})
        assert resp.status_code in (401, 403)

    def test_ui_focus_panel_dispatches(self, auth_headers):
        resp = client.post(
            "/api/v1/commands/ui.focus_panel",
            headers=auth_headers,
            json={"panel_name": "thesis"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["panel"] == "thesis"
        assert body["result"]["ok"] is True


# ─── Concurrency ─────────────────────────────────────────────────────────

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_dispatch_isolates_state(self, auth_headers):
        """Two dispatches run concurrently must each see their own args."""

        class EchoInput(BaseModel):
            token: str

        seen: list = []

        async def _handler(args: dict):
            await asyncio.sleep(0.01)  # force interleave
            seen.append(args["token"])
            return {"token": args["token"]}

        command_registry.register(Command(
            id="test.isolation",
            title="Isolation",
            description="Test concurrent dispatch",
            category="test",
            input_schema=schema_from(EchoInput),
            handler=_handler,
        ))
        try:
            # Dispatch in threads so the sync TestClient does not serialise
            # the requests inside this test's event loop.
            async def _call(tok: str):
                return await asyncio.to_thread(
                    client.post,
                    "/api/v1/commands/test.isolation",
                    headers=auth_headers,
                    json={"token": tok},
                )

            results = await asyncio.gather(*(_call(f"t{i}") for i in range(5)))
            assert all(r.status_code == 200 for r in results)
            tokens = {r.json()["result"]["token"] for r in results}
            assert tokens == {"t0", "t1", "t2", "t3", "t4"}
            assert sorted(seen) == ["t0", "t1", "t2", "t3", "t4"]
        finally:
            command_registry.COMMANDS.pop("test.isolation", None)
