"""
Tests for the Dialectic -> tradingDesk token bridge (web/auth.py).

WHY these exist: td now accepts a JWT minted by a DIFFERENT service. That is
a deliberate hole in the front door, so the tests have to prove the hole is
exactly the shape we meant:

  - a Dialectic ACCESS token for a MAPPED user authenticates as that td user
  - a Dialectic token for an UNMAPPED user is refused
  - a Dialectic REFRESH token (90-day lifetime) is refused
  - a token signed with any other secret is refused
  - ordinary td logins are completely unaffected

The happy-path tokens are minted by Dialectic's OWN create_access_token,
imported from the sibling repo — not by a local reconstruction of its claim
shape. A hand-rolled fixture would keep passing after Dialectic changed its
claims, which is precisely the regression this file exists to catch.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

# WHY: same env trick as test_web.py / test_bridge.py — the JWT secret must be
# deterministic per run and set before web.auth binds it at import time.
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web import auth as auth_mod
from web.auth import User, create_access_token, decode_token, get_current_user
from web.main import app

# Dialectic lives in a sibling repo. Appended (not prepended) so nothing here
# can shadow a td module of the same name.
DIALECTIC_ROOT = Path("/root/DwoodAmo/dialectic")
if str(DIALECTIC_ROOT) not in sys.path:
    sys.path.append(str(DIALECTIC_ROOT))

# Dialectic reads its secret from JWT_SECRET_KEY and caches it on first use.
# Point it at td's test secret so both sides sign with the same key — which is
# exactly the production arrangement this bridge depends on.
os.environ.setdefault("JWT_SECRET_KEY", os.environ["JWT_SECRET"])

try:
    from api.auth.utils import (  # noqa: E402  (path set up above)
        create_access_token as dialectic_access_token,
        create_refresh_token as dialectic_refresh_token,
    )

    DIALECTIC_AVAILABLE = True
except Exception:  # pragma: no cover - only when the sibling repo is absent
    DIALECTIC_AVAILABLE = False

requires_dialectic = pytest.mark.skipif(
    not DIALECTIC_AVAILABLE,
    reason="Dialectic repo not importable — cross-app contract cannot be checked",
)

AMO_UUID = "de883378-a6ef-4af0-a8bc-462265ca7a54"
DAN_UUID = "c9c8f30e-23ad-4730-bb9b-5555e29ae245"
UNMAPPED_UUID = "00000000-0000-4000-8000-000000000abc"


@pytest.fixture
def mapped_users(monkeypatch):
    """Install a known user map. Patched on the module object rather than the
    env var because the map is parsed once at import."""
    monkeypatch.setattr(
        auth_mod, "DIALECTIC_USER_MAP", {AMO_UUID: "amo", DAN_UUID: "dan"}
    )


# --------------------------------------------------------------------------
# A tiny app that mounts the REAL dependency. WHY not only the production app:
# this pins the identity the dependency resolves to, independent of whatever
# any single route does with it.
# --------------------------------------------------------------------------
probe_app = FastAPI()


@probe_app.get("/whoami")
async def whoami(user: User = Depends(get_current_user)):
    return {"username": user.username, "display_name": user.display_name}


probe = TestClient(probe_app, raise_server_exceptions=False)
real_client = TestClient(app, raise_server_exceptions=False)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestDialecticTokenAccepted:
    @requires_dialectic
    def test_mapped_access_token_authenticates_as_td_user(self, mapped_users):
        """A real Dialectic access token for Amo arrives as td user 'amo'."""
        token = dialectic_access_token({"sub": AMO_UUID})
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"username": "amo", "display_name": "Amo"}

    @requires_dialectic
    def test_second_user_maps_independently(self, mapped_users):
        """Dan's uuid must not resolve to Amo — the map is per-user, and a
        bridge that collapsed both onto one identity would misattribute every
        prediction and journal entry Dan writes."""
        token = dialectic_access_token({"sub": DAN_UUID})
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == "dan"

    @requires_dialectic
    def test_decode_token_preserves_dialectic_user_id(self, mapped_users):
        """The originating Dialectic id survives translation, so a bridged
        call can still be attributed back to the Dialectic account."""
        payload = decode_token(dialectic_access_token({"sub": AMO_UUID}))
        assert payload["sub"] == "amo"
        assert payload["dialectic_user_id"] == AMO_UUID

    @requires_dialectic
    def test_uppercase_uuid_in_map_still_matches(self, monkeypatch):
        """The env var is hand-edited; casing must not silently break auth."""
        monkeypatch.setattr(
            auth_mod,
            "DIALECTIC_USER_MAP",
            auth_mod._parse_dialectic_user_map(f"{AMO_UUID.upper()}:AMO"),
        )
        resp = probe.get("/whoami", headers=bearer(dialectic_access_token({"sub": AMO_UUID})))
        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == "amo"


class TestDialecticTokenRefused:
    @requires_dialectic
    def test_unmapped_uuid_is_401(self, mapped_users):
        token = dialectic_access_token({"sub": UNMAPPED_UUID})
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 401
        # The detail must say WHY, not just "invalid" — an unmapped colleague
        # should be told to ask for access, not left debugging a bad token.
        assert "not authorized for tradingDesk" in resp.json()["detail"]

    @requires_dialectic
    def test_refresh_token_is_refused(self, mapped_users):
        """Dialectic's refresh token is valid for 90 days and exists only to
        renew a session. Accepting it here would turn a renewal secret into a
        long-lived API key."""
        token = dialectic_refresh_token({"sub": AMO_UUID})
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 401
        assert "not accepted for API access" in resp.json()["detail"]

    def test_type_claim_with_non_uuid_sub_is_refused(self, mapped_users):
        """A token bearing Dialectic's `type` claim but a username sub must
        not fall through to the local-user path."""
        token = jose_jwt.encode(
            {"sub": "amo", "type": "access", "exp": _future()},
            auth_mod.JWT_SECRET,
            algorithm=auth_mod.JWT_ALGORITHM,
        )
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 401
        assert "not a recognized Dialectic identity" in resp.json()["detail"]

    def test_map_pointing_at_unknown_username_is_refused(self, monkeypatch):
        """A typo in the env var must not conjure a principal with no account."""
        monkeypatch.setattr(auth_mod, "DIALECTIC_USER_MAP", {AMO_UUID: "ghost"})
        token = jose_jwt.encode(
            {"sub": AMO_UUID, "type": "access", "exp": _future()},
            auth_mod.JWT_SECRET,
            algorithm=auth_mod.JWT_ALGORITHM,
        )
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 401
        assert "does not exist" in resp.json()["detail"]

    def test_empty_map_refuses_every_dialectic_token(self, monkeypatch):
        """Bridge disabled (unset env) must fail closed, not open."""
        monkeypatch.setattr(auth_mod, "DIALECTIC_USER_MAP", {})
        token = jose_jwt.encode(
            {"sub": AMO_UUID, "type": "access", "exp": _future()},
            auth_mod.JWT_SECRET,
            algorithm=auth_mod.JWT_ALGORITHM,
        )
        assert probe.get("/whoami", headers=bearer(token)).status_code == 401

    def test_token_signed_with_a_different_secret_is_refused(self, mapped_users):
        """The shared secret is the whole trust anchor. If a token signed with
        another key were accepted, the map would be the only thing standing
        between a stranger and the desk."""
        token = jose_jwt.encode(
            {"sub": AMO_UUID, "type": "access", "exp": _future()},
            "some-other-services-secret",
            algorithm="HS256",
        )
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired token"

    @requires_dialectic
    def test_expired_dialectic_token_is_refused(self, mapped_users):
        from datetime import timedelta

        token = dialectic_access_token(
            {"sub": AMO_UUID}, expires_delta=timedelta(minutes=-5)
        )
        assert probe.get("/whoami", headers=bearer(token)).status_code == 401


class TestLocalLoginUnaffected:
    def test_ordinary_td_token_still_works(self, mapped_users):
        token = create_access_token("amo", "Amo")
        resp = probe.get("/whoami", headers=bearer(token))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"username": "amo", "display_name": "Amo"}

    def test_td_token_works_with_bridge_disabled(self, monkeypatch):
        """Local auth must not depend on the bridge being configured at all."""
        monkeypatch.setattr(auth_mod, "DIALECTIC_USER_MAP", {})
        resp = probe.get("/whoami", headers=bearer(create_access_token("dan", "Dan")))
        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == "dan"

    def test_garbage_token_is_401(self):
        resp = probe.get("/whoami", headers=bearer("not-a-real-jwt"))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired token"

    def test_no_token_is_401(self):
        assert probe.get("/whoami").status_code == 401


class TestUserMapParsing:
    def test_parses_two_pairs(self):
        parsed = auth_mod._parse_dialectic_user_map(f"{AMO_UUID}:amo,{DAN_UUID}:dan")
        assert parsed == {AMO_UUID: "amo", DAN_UUID: "dan"}

    def test_empty_string_yields_empty_map(self):
        assert auth_mod._parse_dialectic_user_map("") == {}

    def test_tolerates_whitespace_and_trailing_comma(self):
        parsed = auth_mod._parse_dialectic_user_map(f" {AMO_UUID} : Amo , ")
        assert parsed == {AMO_UUID: "amo"}

    def test_skips_malformed_entries_but_keeps_good_ones(self):
        """One typo must not take the whole desk's auth offline."""
        with pytest.warns(UserWarning):
            parsed = auth_mod._parse_dialectic_user_map(
                f"not-a-uuid:bob,{AMO_UUID}:amo,missing-colon"
            )
        assert parsed == {AMO_UUID: "amo"}


class TestRealAppRequestPath:
    """The probe app proves the dependency; these prove the REAL app's routes
    go through it. Both assertions matter: without the no-token 401 the
    'not 401' check would pass vacuously against a route that 404s."""

    ROUTE = "/api/predictions"

    def test_real_route_rejects_anonymous(self):
        assert real_client.get(self.ROUTE).status_code in (401, 403)

    @requires_dialectic
    def test_real_route_accepts_bridged_token(self, mapped_users):
        resp = real_client.get(
            self.ROUTE, headers=bearer(dialectic_access_token({"sub": AMO_UUID}))
        )
        # Any non-auth status is fine here (the repo may be empty or unavailable
        # in CI); what is being asserted is that auth no longer rejects it.
        assert resp.status_code not in (401, 403), resp.text

    @requires_dialectic
    def test_real_route_still_rejects_unmapped_bridged_token(self, mapped_users):
        resp = real_client.get(
            self.ROUTE, headers=bearer(dialectic_access_token({"sub": UNMAPPED_UUID}))
        )
        assert resp.status_code == 401


def _future() -> int:
    from datetime import datetime, timedelta, timezone

    return int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())


def test_uuid_fixtures_are_well_formed():
    """Guards the fixtures themselves — a malformed constant here would make
    several refusal tests pass for the wrong reason."""
    for value in (AMO_UUID, DAN_UUID, UNMAPPED_UUID):
        assert str(uuid.UUID(value)) == value
