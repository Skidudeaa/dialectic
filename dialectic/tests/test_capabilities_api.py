"""
HTTP contract for GET /auth/capabilities (api/capabilities.py).

WHY this endpoint exists: the signed-out screen has to tell a new user which
doors are actually open, and it renders before any credential exists. Today it
offers a Create Account form that fills in three fields and only then discovers
a 403 — because the frontend has no way to ask.

WHAT THESE TESTS ARE REALLY FENCING: drift. A capability endpoint that reads its
own copy of the environment is a second source of truth, and the moment the two
disagree the UI advertises a door the server refuses. So the endpoint must
delegate to the SAME predicate the signup route enforces with, and the decisive
test here is the one that flips the environment and watches the answer follow.
"""

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.auth import routes as auth_routes

PATH = "/auth/capabilities"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def test_it_lives_under_a_prefix_the_edge_actually_proxies() -> None:
    """The trap that a passing endpoint test cannot see.

    nginx proxies ONE hardcoded list of prefixes to this backend, and
    vite.config.ts mirrors it for dev/preview. A path outside that list is
    answered by the SPA fallback with 200 + index.html, so the browser parses
    HTML as JSON, the fetch throws, and the screen silently keeps its default.

    It would look fine here forever: every test in this file drives the ASGI app
    directly and never crosses the edge. The first tidy-looking rename to
    /meta/capabilities reintroduces it — and on this deployment the symptom is
    invisible, because the default the screen falls back to happens to be the
    correct answer today.
    """
    assert PATH.startswith("/auth/"), (
        "Capabilities must stay under an nginx-proxied prefix. If you move it, "
        "add the new prefix to BOTH sites-available/dialectic and the proxyMap "
        "in vite.config.ts in the same change."
    )


def test_capabilities_needs_no_credential() -> None:
    """It renders before login, so it must answer without one."""
    response = TestClient(main_mod.app).get(PATH)
    assert response.status_code == 200


def test_reports_signups_closed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SIGNUPS_ENABLED", raising=False)
    response = TestClient(main_mod.app).get(PATH)
    assert response.json()["signups_enabled"] is False


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("on", True),
     ("0", False), ("", False), ("banana", False)],
)
def test_the_answer_follows_the_real_gate(monkeypatch, value, expected) -> None:
    """The drift guard, and the reason this file exists.

    Reading `SIGNUPS_ENABLED` a second time here would pass this test while
    still being wrong the day the signup route's own rule changes shape. The
    endpoint calls `_signups_enabled()` — the predicate the route ENFORCES
    with — so the advertised state and the enforced state cannot disagree.
    """
    monkeypatch.setenv("SIGNUPS_ENABLED", value)
    response = TestClient(main_mod.app).get(PATH)
    assert response.json()["signups_enabled"] is expected
    # And it agrees with the enforcing predicate itself, not merely with our
    # expectation of it.
    assert response.json()["signups_enabled"] is auth_routes._signups_enabled()


def test_it_is_the_same_predicate_not_a_copy_of_it() -> None:
    """The mutation every other test in this file CANNOT catch.

    A faithful copy satisfies all of them — same variable, same truthy set — and
    a behavioural probe cannot tell the two apart, because both answer
    identically until the day the rule changes shape. Even patching the name the
    endpoint calls proves nothing: that works whether the name was imported or
    defined locally.

    Identity is the only assertion that distinguishes them. Verified by running
    the mutation: swapping the import for a locally-defined equivalent leaves
    every behavioural test green and turns THIS one red.
    """
    import api.capabilities as capabilities_mod

    assert capabilities_mod._signups_enabled is auth_routes._signups_enabled


def test_exposes_no_secret(monkeypatch) -> None:
    """Unauthenticated surface: booleans about doors, never configuration."""
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-value-not-for-the-wire")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-never-appear")
    body = TestClient(main_mod.app).get(PATH).text
    assert "super-secret-value-not-for-the-wire" not in body
    assert "sk-ant-must-never-appear" not in body
    # Every value is a plain boolean — nothing here can carry a credential.
    for value in TestClient(main_mod.app).get(PATH).json().values():
        assert isinstance(value, bool)
