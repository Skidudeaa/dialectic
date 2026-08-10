"""Where a Dialectic room token comes from.

WHY this module exists: the five per-room tokens lived in `books/*.json`
under `meta.dialecticRoomToken`, which put live credentials in a tracked
file — and on 2026-08-10 that tree was pushed to a PUBLIC GitHub repo. The
owner's call was to move them, not rotate them: the secrets are unchanged,
only their home moved, so nothing on either side of the bridge needs to
learn a new value.

That makes the ONLY risk of this migration a reader we failed to find. So
every consumer now asks here instead of reaching into `meta` itself, and
there is exactly one place that knows the answer:

    DIALECTIC_ROOM_TOKENS   "<room-uuid>:<token>,<room-uuid>:<token>"
    meta.dialecticRoomToken back-compat for a checkout that still has one
    DIALECTIC_ROOM_TOKEN    legacy single-room setups

WHY env wins over the book: after the scrub the books carry nothing, but a
stale checkout might — and if the two ever disagree, the operator's
environment is the one they can change without a commit.

WHY the shape mirrors DIALECTIC_USER_MAP (`web/auth.py`): same problem,
same house answer — comma-separated `key:value` pairs, UUID-keyed and
canonicalised so casing cannot silently fail to match, malformed entries
warned about and skipped rather than raised. One typo must not take the
whole desk's push path offline at boot.

Stdlib only, and it lives under `tools/` on purpose: that tree is
zero-dependency and `run-all.py` has to keep working standalone. `web/`
imports from here, never the reverse.
"""

from __future__ import annotations

import os
import uuid as _uuid
import warnings
from typing import Mapping, Optional

ENV_ROOM_TOKENS = "DIALECTIC_ROOM_TOKENS"
ENV_ROOM_TOKEN_SINGLE = "DIALECTIC_ROOM_TOKEN"


def parse_room_tokens(raw: str) -> dict:
    """Parse `uuid:token,uuid:token` into {canonical_uuid: token}.

    An empty or absent value yields {}, which simply means "no tokens
    configured here" — the caller then falls through to its other sources.
    """
    mapping: dict = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        raw_uuid, sep, token = pair.partition(":")
        if not sep or not token.strip():
            warnings.warn(
                f"{ENV_ROOM_TOKENS}: skipping malformed entry (expected "
                f"uuid:token) for key {raw_uuid.strip()!r}",
                stacklevel=2,
            )
            continue
        try:
            key = str(_uuid.UUID(raw_uuid.strip()))
        except ValueError:
            warnings.warn(
                f"{ENV_ROOM_TOKENS}: skipping entry with non-UUID key "
                f"{raw_uuid.strip()!r}",
                stacklevel=2,
            )
            continue
        mapping[key] = token.strip()
    return mapping


def _canonical(room_id: Optional[str]) -> Optional[str]:
    if not room_id:
        return None
    try:
        return str(_uuid.UUID(str(room_id).strip()))
    except ValueError:
        return None


def resolve_room_token(
    meta: Optional[Mapping], *, env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """The token for the room this book pushes to, or None.

    `meta` is a book's `meta` block — it supplies `dialecticRoomId`, which
    is the key into the env map. Returns None when nothing is configured;
    callers already treat that as "this book does not push", which is the
    behaviour a book with no room has always had.
    """
    env = os.environ if env is None else env
    meta = meta or {}

    room_id = _canonical(meta.get("dialecticRoomId"))
    if room_id:
        token = parse_room_tokens(env.get(ENV_ROOM_TOKENS, "")).get(room_id)
        if token:
            return token

    book_token = (meta.get("dialecticRoomToken") or "").strip()
    if book_token:
        # Not fatal — a checkout predating the migration still works — but
        # this is a live credential sitting in a tracked file, which is the
        # exact condition that put five of them on a public repo.
        warnings.warn(
            "meta.dialecticRoomToken is deprecated and must not be committed; "
            f"move it into {ENV_ROOM_TOKENS} as '<room-uuid>:<token>'",
            stacklevel=2,
        )
        return book_token

    single = (env.get(ENV_ROOM_TOKEN_SINGLE) or "").strip()
    return single or None
