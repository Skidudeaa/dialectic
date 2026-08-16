"""Regression tests for authentication abuse controls and recovery truth."""

import os
from unittest.mock import AsyncMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.main as main_mod
import api.auth.routes as auth_routes
from api.rate_limit import (
    RateLimiter,
    check_account_rate_limit,
    check_rate_limit,
    rate_limiter,
)


@pytest.fixture(autouse=True)
def clear_rate_limit_buckets() -> None:
    rate_limiter._requests.clear()


@pytest.fixture
def db() -> AsyncMock:
    fake = AsyncMock()
    fake.fetchrow.return_value = None
    return fake


@pytest.fixture
def client(db: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(
        auth_routes.router,
        prefix="/auth",
        dependencies=[Depends(check_rate_limit)],
    )

    async def get_test_db():
        yield db

    app.dependency_overrides[auth_routes.get_db] = get_test_db
    return TestClient(app, raise_server_exceptions=False)


def test_auth_openapi_does_not_expose_rate_policy() -> None:
    operation = main_mod.app.openapi()["paths"]["/auth/login"]["post"]
    names = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert names.isdisjoint({"limit", "window"})


def test_limiter_evicts_expired_keys() -> None:
    now = [100.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert limiter.is_allowed("ip:/auth/login", 1, 60)
    now[0] = 3701.0
    assert limiter.is_allowed("other", 1, 60)
    assert "ip:/auth/login" not in limiter._requests


def test_sixth_login_attempt_for_one_account_is_limited(client: TestClient) -> None:
    body = {"email": "a@example.com", "password": "wrong-password"}
    for _ in range(5):
        assert client.post("/auth/login", json=body).status_code != 429
    assert client.post("/auth/login", json=body).status_code == 429


def test_forgot_password_is_unavailable_without_creating_a_code(
    client: TestClient,
    db: AsyncMock,
) -> None:
    response = client.post(
        "/auth/forgot-password",
        json={"email": "known@example.com"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Password recovery is unavailable because email delivery is not configured"
    )
    assert not any(
        "verification_codes" in call.args[0]
        for call in db.execute.await_args_list
    )


def test_account_limit_survives_ip_rotation_without_storing_email() -> None:
    for attempt in range(5):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/auth/login",
                "headers": [],
                "client": (f"192.0.2.{attempt + 1}", 4000),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )
        check_account_rate_limit(
            request,
            "  A@Example.com ",
            scope="login",
            limit=5,
            window_seconds=900,
        )

    sixth_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [],
            "client": ("192.0.2.99", 4000),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        check_account_rate_limit(
            sixth_request,
            "a@example.com",
            scope="login",
            limit=5,
            window_seconds=900,
        )
    assert getattr(exc_info.value, "status_code", None) == 429
    assert all("a@example.com" not in key for key in rate_limiter._requests)


def test_forgot_password_uses_the_three_attempt_policy(client: TestClient) -> None:
    body = {"email": "known@example.com"}
    assert [
        client.post("/auth/forgot-password", json=body).status_code
        for _ in range(4)
    ] == [503, 503, 503, 429]


def test_reset_hides_whether_the_account_exists(
    client: TestClient,
    db: AsyncMock,
) -> None:
    body = {
        "email": "unknown@example.com",
        "code": "123456",
        "new_password": "a-new-long-password",
    }
    unknown = client.post("/auth/reset-password", json=body)

    db.fetchrow.reset_mock()
    db.fetchrow.side_effect = [{"user_id": "ignored"}, None]
    body["email"] = "known@example.com"
    invalid_code = client.post("/auth/reset-password", json=body)

    assert unknown.status_code == invalid_code.status_code == 400
    assert unknown.json() == invalid_code.json() == {
        "detail": "Invalid or expired reset code"
    }
