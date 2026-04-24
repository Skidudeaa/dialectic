"""
Tests for the CORS relay (web/routes/relay.py).

Coverage:
- Allowlist enforcement: host, path prefix, scheme, userinfo
- Malformed / missing URL parameter rejection
- Rate limit trip
- Upstream passthrough: 2xx body + content-type
- Upstream 5xx passthrough (Yahoo returning 500 still reaches the client)
- Upstream timeout → 504
- Oversize upstream body → 502
- Cache-Control header on success
- Non-GET rejected by FastAPI automatically
"""
from __future__ import annotations

import os
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")
# High limit so non-rate-limit tests don't trip the default 60/min.
os.environ["RELAY_RATE_LIMIT_PER_MIN"] = "1000"

from web.main import app  # noqa: E402
from web.routes import relay as relay_module  # noqa: E402

client = TestClient(app)

ALLOWED_URL = (
    "https://query1.finance.yahoo.com/v7/finance/spark"
    "?symbols=CL=F&range=1d&interval=1d"
)
ALLOWED_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/CL=F"
    "?range=5d&interval=1d"
)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Rate-limiter deque is module-scoped; reset between cases."""
    relay_module.rate_limiter.reset()
    yield
    relay_module.rate_limiter.reset()


def _mock_client(
    *,
    status_code: int = 200,
    content: bytes = b'{"spark":{"result":[]}}',
    content_type: str = "application/json",
    raises: Optional[Exception] = None,
):
    """Build a patch target for `httpx.AsyncClient` used inside the relay.

    The relay uses `async with httpx.AsyncClient(...) as client: await client.get(...)`.
    We mock the class so its instance is an async context manager whose `.get`
    returns a response mock (or raises).
    """

    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = content
    response.headers = {"content-type": content_type}

    instance = MagicMock()
    if raises is not None:
        instance.get = AsyncMock(side_effect=raises)
    else:
        instance.get = AsyncMock(return_value=response)

    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)

    cls = MagicMock(return_value=instance)
    return patch("web.routes.relay.httpx.AsyncClient", cls), instance


# ── Happy path ───────────────────────────────────────────────────────────

def test_allowed_spark_url_passes_through():
    patcher, instance = _mock_client(content=b'{"hello":"world"}')
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}
    assert r.headers["cache-control"] == "public, max-age=30"
    # Upstream URL was forwarded exactly.
    forwarded = instance.get.await_args.args[0]
    assert forwarded == ALLOWED_URL


def test_allowed_chart_url_passes_through():
    patcher, _ = _mock_client(content=b'{"chart":{"result":[]}}')
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_CHART_URL})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=30"


def test_upstream_content_type_is_preserved():
    patcher, _ = _mock_client(content=b"xml here", content_type="application/xml")
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 200
    # Starlette may append charset; check the prefix.
    assert r.headers["content-type"].startswith("application/xml")


# ── Allowlist enforcement ────────────────────────────────────────────────

@pytest.mark.parametrize("bad_url,reason_substr", [
    # Wrong host
    ("https://evil.example.com/v7/finance/spark?x=1", "host not allowlisted"),
    # query2 is legacy-but-unapproved; only query1 is allowlisted
    ("https://query2.finance.yahoo.com/v7/finance/spark?x=1", "host not allowlisted"),
    # Wrong path
    ("https://query1.finance.yahoo.com/v9/something?x=1", "path not allowlisted"),
    # http, not https
    ("http://query1.finance.yahoo.com/v7/finance/spark?x=1", "scheme must be https"),
    # userinfo
    ("https://user:pass@query1.finance.yahoo.com/v7/finance/spark", "userinfo"),
])
def test_off_allowlist_rejected(bad_url, reason_substr):
    r = client.get("/api/relay/yahoo", params={"url": bad_url})
    assert r.status_code == 400
    assert reason_substr.lower() in r.json()["detail"].lower()


def test_empty_url_rejected():
    r = client.get("/api/relay/yahoo", params={"url": ""})
    assert r.status_code == 400


def test_url_param_missing_rejected():
    # FastAPI will 422 for a missing required query param.
    r = client.get("/api/relay/yahoo")
    assert r.status_code == 422


def test_oversized_url_rejected():
    # 3000-char URL — still starts with an allowlisted prefix but exceeds the
    # 2048 cap inside _validate_upstream.
    long_url = (
        "https://query1.finance.yahoo.com/v7/finance/spark?symbols="
        + ("X" * 3000)
    )
    r = client.get("/api/relay/yahoo", params={"url": long_url})
    assert r.status_code == 400
    assert "too long" in r.json()["detail"].lower()


# ── Upstream passthrough ─────────────────────────────────────────────────

def test_upstream_5xx_passthrough():
    """Yahoo returning 503 should proxy as 503 — the caller needs to see it."""
    patcher, _ = _mock_client(status_code=503, content=b'{"error":"upstream down"}')
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 503
    assert r.json() == {"error": "upstream down"}


def test_upstream_timeout_maps_to_504():
    patcher, _ = _mock_client(raises=httpx.TimeoutException("upstream timeout"))
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 504
    assert "timeout" in r.json()["detail"].lower()


def test_upstream_connection_error_maps_to_502():
    patcher, _ = _mock_client(raises=httpx.ConnectError("boom"))
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 502


def test_oversize_upstream_body_rejected():
    # Build a body above the 512 KiB cap.
    big = b"A" * (relay_module.MAX_UPSTREAM_BYTES + 1)
    patcher, _ = _mock_client(content=big)
    with patcher:
        r = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 502
    assert "too large" in r.json()["detail"].lower()


# ── Rate limit ───────────────────────────────────────────────────────────

def test_rate_limit_trips_after_threshold(monkeypatch):
    # Lower the limiter's window to 2/min so the test is fast.
    small = relay_module._IPRateLimiter(per_minute=2)
    monkeypatch.setattr(relay_module, "rate_limiter", small)

    patcher, _ = _mock_client(content=b"{}")
    with patcher:
        assert client.get("/api/relay/yahoo", params={"url": ALLOWED_URL}).status_code == 200
        assert client.get("/api/relay/yahoo", params={"url": ALLOWED_URL}).status_code == 200
        third = client.get("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert third.status_code == 429
    assert "rate" in third.json()["detail"].lower()


# ── Method guard ─────────────────────────────────────────────────────────

def test_post_not_allowed():
    """FastAPI should 405 automatically; relay only registers GET."""
    r = client.post("/api/relay/yahoo", params={"url": ALLOWED_URL})
    assert r.status_code == 405
