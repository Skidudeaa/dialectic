"""The application must not advertise startup without its required database."""

from unittest.mock import AsyncMock

import pytest

import api.main as main_mod


@pytest.mark.asyncio
async def test_database_pool_failure_aborts_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_mod, "_validate_environment", lambda: None)
    monkeypatch.setattr(main_mod.asyncpg, "create_pool", AsyncMock(
        side_effect=OSError("postgres down"),
    ))
    monkeypatch.setattr(main_mod, "db_pool", None)

    with pytest.raises(OSError, match="postgres down"):
        async with main_mod.lifespan(main_mod.app):
            pass
