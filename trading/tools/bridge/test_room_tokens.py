"""Tests for room-token resolution.

WHY these matter more than most: the migration on 2026-08-10 moved five LIVE
credentials out of `books/*.json` and into the environment WITHOUT rotating
them — the owner's explicit call. That makes the failure mode asymmetric. A
reader we failed to find does not raise; it resolves to None, the caller
treats the book as "does not push", and the room simply goes quiet. So the
tests that count are the ones that pin the precedence, the ones that prove
no shipped book still carries a token, and the one that proves every book
can still find its token now that the books are empty.
"""

import json
import os
from pathlib import Path

import pytest

from tools.bridge.room_tokens import (
    ENV_ROOM_TOKEN_SINGLE,
    ENV_ROOM_TOKENS,
    ENV_ROOM_TOKENS_FILE,
    load_file_tokens,
    parse_room_tokens,
    register_room_token,
    resolve_room_token,
)

BOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "books"
ROOM_A = "56ba2f1e-5c70-4290-a77d-52404f0095da"
ROOM_B = "8adcabb7-817a-4802-87c6-3bfd42e6a9eb"


class TestParse:
    def test_parses_pairs(self):
        got = parse_room_tokens(f"{ROOM_A}:tok-a,{ROOM_B}:tok-b")
        assert got == {ROOM_A: "tok-a", ROOM_B: "tok-b"}

    def test_empty_is_empty(self):
        assert parse_room_tokens("") == {}
        assert parse_room_tokens("   ") == {}

    def test_whitespace_and_trailing_comma_are_tolerated(self):
        assert parse_room_tokens(f" {ROOM_A} : tok-a , ") == {ROOM_A: "tok-a"}

    def test_uppercase_uuid_still_matches(self):
        """A casing difference in the env must not silently fail to match."""
        got = parse_room_tokens(f"{ROOM_A.upper()}:tok-a")
        assert got == {ROOM_A: "tok-a"}

    def test_one_bad_entry_does_not_lose_the_others(self):
        """A typo must not take the whole push path offline at boot."""
        with pytest.warns(UserWarning):
            got = parse_room_tokens(f"not-a-uuid:x,{ROOM_A}:tok-a")
        assert got == {ROOM_A: "tok-a"}

    def test_a_valueless_entry_is_skipped(self):
        with pytest.warns(UserWarning):
            assert parse_room_tokens(f"{ROOM_A}:") == {}


class TestResolve:
    def test_env_map_supplies_the_token(self):
        meta = {"dialecticRoomId": ROOM_A}
        env = {ENV_ROOM_TOKENS: f"{ROOM_A}:from-env"}
        assert resolve_room_token(meta, env=env) == "from-env"

    def test_env_beats_a_stale_book_value(self):
        """The operator can fix a token without a commit."""
        meta = {"dialecticRoomId": ROOM_A, "dialecticRoomToken": "stale"}
        env = {ENV_ROOM_TOKENS: f"{ROOM_A}:from-env"}
        assert resolve_room_token(meta, env=env) == "from-env"

    def test_a_book_token_still_works_but_warns(self):
        """Back-compat for a checkout predating the migration."""
        meta = {"dialecticRoomId": ROOM_A, "dialecticRoomToken": "from-book"}
        with pytest.warns(UserWarning, match="deprecated"):
            assert resolve_room_token(meta, env={}) == "from-book"

    def test_legacy_single_token_is_the_last_resort(self):
        meta = {"dialecticRoomId": ROOM_A}
        env = {ENV_ROOM_TOKEN_SINGLE: "legacy"}
        assert resolve_room_token(meta, env=env) == "legacy"

    def test_the_map_wins_over_the_legacy_single(self):
        meta = {"dialecticRoomId": ROOM_A}
        env = {ENV_ROOM_TOKENS: f"{ROOM_A}:mapped",
               ENV_ROOM_TOKEN_SINGLE: "legacy"}
        assert resolve_room_token(meta, env=env) == "mapped"

    def test_a_room_absent_from_the_map_gets_nothing(self):
        meta = {"dialecticRoomId": ROOM_B}
        env = {ENV_ROOM_TOKENS: f"{ROOM_A}:only-a"}
        assert resolve_room_token(meta, env=env) is None

    def test_no_room_id_and_no_config_is_none(self):
        assert resolve_room_token({}, env={}) is None
        assert resolve_room_token(None, env={}) is None

    def test_a_malformed_room_id_does_not_raise(self):
        meta = {"dialecticRoomId": "not-a-uuid"}
        env = {ENV_ROOM_TOKENS: f"{ROOM_A}:tok"}
        assert resolve_room_token(meta, env=env) is None


class TestFileTier:
    """The runtime file that lets a Dialectic-created thesis push without a
    desk restart. Env must still win; the file must stay 0600; a missing
    file must be silence, because that is every box before the first
    created thesis."""

    def _env(self, tmp_path):
        return {ENV_ROOM_TOKENS_FILE: str(tmp_path / "room-tokens.env")}

    def test_register_then_resolve_round_trips(self, tmp_path):
        env = self._env(tmp_path)
        register_room_token(ROOM_A, "tok-file", env=env)
        assert resolve_room_token({"dialecticRoomId": ROOM_A}, env=env) == "tok-file"

    def test_env_map_beats_the_file(self, tmp_path):
        """The operator's environment remains the last word."""
        env = self._env(tmp_path)
        env[ENV_ROOM_TOKENS] = f"{ROOM_A}:from-env"
        register_room_token(ROOM_A, "from-file", env=env)
        assert resolve_room_token({"dialecticRoomId": ROOM_A}, env=env) == "from-env"

    def test_reregistering_replaces_without_losing_others(self, tmp_path):
        env = self._env(tmp_path)
        register_room_token(ROOM_A, "tok-a", env=env)
        register_room_token(ROOM_B, "tok-b", env=env)
        register_room_token(ROOM_A, "tok-a2", env=env)
        assert load_file_tokens(env) == {ROOM_A: "tok-a2", ROOM_B: "tok-b"}

    def test_the_file_is_owner_only(self, tmp_path):
        env = self._env(tmp_path)
        path = register_room_token(ROOM_A, "tok", env=env)
        assert os.stat(path).st_mode & 0o777 == 0o600

    def test_a_missing_file_is_silence(self, tmp_path):
        assert load_file_tokens(self._env(tmp_path)) == {}
        assert resolve_room_token(
            {"dialecticRoomId": ROOM_A}, env=self._env(tmp_path)
        ) is None

    def test_register_rejects_garbage(self, tmp_path):
        env = self._env(tmp_path)
        with pytest.raises(ValueError):
            register_room_token("not-a-uuid", "tok", env=env)
        with pytest.raises(ValueError):
            register_room_token(ROOM_A, "   ", env=env)
        with pytest.raises(ValueError):
            register_room_token(ROOM_A, "with:delimiter", env=env)

    def test_uppercase_registration_still_resolves(self, tmp_path):
        env = self._env(tmp_path)
        register_room_token(ROOM_A.upper(), "tok", env=env)
        assert resolve_room_token({"dialecticRoomId": ROOM_A}, env=env) == "tok"


class TestShippedBooks:
    def test_no_book_carries_a_token(self):
        """The whole point of the migration — and the regression guard.

        `builder.py` re-writes book JSON on save and preserves meta keys it
        finds, so a token reintroduced once would persist silently.
        """
        for path in sorted(BOOKS_DIR.glob("*.json")):
            meta = json.loads(path.read_text()).get("meta", {}) or {}
            assert "dialecticRoomToken" not in meta, (
                f"{path.name} carries a live credential — the books are on a "
                f"PUBLIC repo; put it in {ENV_ROOM_TOKENS} instead"
            )

    def test_every_book_with_a_room_can_still_find_its_token(self):
        """The books are empty now, so this fails if the env is not wired.

        Skips when the env is absent (a fresh checkout / CI), because that
        is a deployment fact rather than a code defect — but on the box that
        runs the desk, this is the test that catches a half-done migration.
        """
        if not os.environ.get(ENV_ROOM_TOKENS):
            pytest.skip(f"{ENV_ROOM_TOKENS} not set in this environment")
        for path in sorted(BOOKS_DIR.glob("*.json")):
            meta = json.loads(path.read_text()).get("meta", {}) or {}
            if not meta.get("dialecticRoomId"):
                continue
            assert resolve_room_token(meta), (
                f"{path.name} declares a room but no token resolves for it — "
                f"its push path is silently dead"
            )
