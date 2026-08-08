"""Web Push channel: send, prune-on-410, and unconfigured-disable behavior."""

import pytest

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
