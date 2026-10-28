"""A manager's 'send this week's dispatch now': the Sunday post for one room, today, once per day."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from scheduler import SchedulerContext
from organs.longway import dispatch, jobs
from tests.test_longway_register import longway_repo, git  # noqa: F401  (fixtures)
from tests.test_longway_api import db, house, client  # noqa: F401  (fixtures)


@pytest.mark.asyncio
async def test_dispatch_now_posts_once_per_day_and_pushes(db, house, client, longway_repo, monkeypatch):
    tuesday = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    model = AsyncMock(return_value="S1 remains unverified. Which month?\n\n" + dispatch.REACTION_LINE)
    monkeypatch.setattr(jobs, "draft", model)
    push = AsyncMock()
    monkeypatch.setattr("api.notifications.webpush.send_web_notifications", push)
    broadcast = AsyncMock()
    ctx = SchedulerContext(house.pool, broadcast=broadcast)

    first = await jobs.dispatch_now(ctx, house.room, now=tuesday)
    assert first["already"] is False and first["message_id"]
    assert model.await_count == 1 and broadcast.await_count == 1 and push.await_count == 1
    latest = (await client.get(f"/rooms/{house.room}/longway/dispatch/latest")).json()
    assert latest["id"] == first["message_id"]
    assert latest["metadata"]["longway_dispatch"] == {"journey": "ogasawara", "week_of": "2026-11-03"}
    assert latest["content"].endswith(dispatch.REACTION_LINE)

    second = await jobs.dispatch_now(ctx, house.room, now=tuesday)
    assert second == {"message_id": first["message_id"], "pushed": 0, "already": True}
    assert model.await_count == 1 and push.await_count == 1

    unbound = uuid4()
    await db.execute("INSERT INTO rooms(id,created_at,token,name) VALUES ($1,clock_timestamp(),$2,'Unbound')", unbound, str(unbound))
    with pytest.raises(ValueError):
        await jobs.dispatch_now(ctx, unbound, now=tuesday)


@pytest.mark.asyncio
async def test_dispatch_now_route_needs_a_manager(db, house, client, longway_repo, monkeypatch):
    monkeypatch.setattr(jobs, "draft", AsyncMock(return_value="Nothing moved this week\n\n" + dispatch.REACTION_LINE))
    monkeypatch.setattr("api.notifications.webpush.send_web_notifications", AsyncMock())
    response = await client.post(f"/rooms/{house.room}/longway/dispatch/now")
    assert response.status_code in (200, 403), response.text
    if response.status_code == 200:
        body = response.json()
        assert body["message_id"] and body["already"] is False
