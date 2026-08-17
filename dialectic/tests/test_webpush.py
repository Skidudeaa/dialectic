"""Web Push channel and room-aware message notification contracts."""

from unittest.mock import AsyncMock

import pytest

from api.notifications.service import PushNotificationService
from api.notifications import webpush


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeDB:
    """Records executes; returns canned subscription rows."""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    async def fetch(self, query, *args):
        return self.rows

    async def execute(self, query, *args):
        self.executed.append((" ".join(query.split()), args))


def sub_row(sub_id="s1"):
    return {"id": sub_id, "endpoint": f"https://push.example/{sub_id}",
            "p256dh": "k", "auth": "a"}


@pytest.fixture
def vapid_env(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "test-key")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")


@pytest.mark.asyncio
async def test_send_success_stamps_last_success(vapid_env, monkeypatch):
    monkeypatch.setattr(webpush, "_send_one", lambda *a: None)
    db = FakeDB([sub_row()])
    result = await webpush.send_web_notifications(
        db, ["u1"], "Amo", "hello", {"room_id": "r1"})
    assert result["sent"] == 1 and result["errors"] == []
    assert any("last_success_at" in q for q, _ in db.executed)


@pytest.mark.asyncio
async def test_gone_subscription_is_pruned(vapid_env, monkeypatch):
    def raise_gone(*a):
        exc = webpush.WebPushException("gone")
        exc.response = FakeResponse(410)
        raise exc
    monkeypatch.setattr(webpush, "_send_one", raise_gone)
    db = FakeDB([sub_row()])
    result = await webpush.send_web_notifications(
        db, ["u1"], "Amo", "hello", {"room_id": "r1"})
    assert result["sent"] == 0
    assert any(q.startswith("DELETE FROM web_push_subscriptions") for q, _ in db.executed)


@pytest.mark.asyncio
async def test_transient_failure_keeps_subscription(vapid_env, monkeypatch):
    def raise_5xx(*a):
        exc = webpush.WebPushException("bad gateway")
        exc.response = FakeResponse(502)
        raise exc
    monkeypatch.setattr(webpush, "_send_one", raise_5xx)
    db = FakeDB([sub_row()])
    result = await webpush.send_web_notifications(
        db, ["u1"], "Amo", "hello", {"room_id": "r1"})
    assert result["sent"] == 0 and len(result["errors"]) == 1
    assert not any(q.startswith("DELETE") for q, _ in db.executed)


@pytest.mark.asyncio
async def test_unconfigured_vapid_disables_cleanly(monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    db = FakeDB([sub_row()])
    result = await webpush.send_web_notifications(
        db, ["u1"], "Amo", "hello", {})
    assert result == {"sent": 0, "errors": ["vapid_unconfigured"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_llm,sender_name,expected_title",
    [
        (False, "Amo", "Iran/Hormuz Trading Room · Amo"),
        (True, "Claude", "Iran/Hormuz Trading Room · ✦ Claude"),
    ],
)
async def test_message_notification_title_and_data_name_the_room(
    monkeypatch, is_llm, sender_name, expected_title,
):
    send_web = AsyncMock(return_value={"sent": 1, "errors": []})
    monkeypatch.setattr(webpush, "send_web_notifications", send_web)
    db = FakeDB([{
        "user_id": "u1",
        "expo_push_token": "ExponentPushToken[test]",
    }])
    service = PushNotificationService()
    service._send_batch = AsyncMock(return_value={"sent": 1, "errors": []})

    await service.send_message_notification(
        db=db,
        recipient_user_ids=["u1"],
        room_id="r1",
        room_name="Iran/Hormuz Trading Room",
        thread_id="t1",
        message_id="m1",
        sender_name=sender_name,
        content="A current message",
        is_llm=is_llm,
    )

    web_kwargs = send_web.await_args.kwargs
    assert web_kwargs["title"] == expected_title
    assert web_kwargs["data"] == {
        "room_id": "r1",
        "room_name": "Iran/Hormuz Trading Room",
        "thread_id": "t1",
        "message_id": "m1",
        "type": "new_message",
    }
    expo_message = service._send_batch.await_args.args[1][0]
    assert expo_message.title == expected_title
    assert expo_message.data == web_kwargs["data"]
