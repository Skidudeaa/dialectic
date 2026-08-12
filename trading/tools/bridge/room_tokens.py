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

    DIALECTIC_ROOM_TOKENS        "<room-uuid>:<token>,<room-uuid>:<token>"
    DIALECTIC_ROOM_TOKENS_FILE   path to a runtime token file (default
                                 /var/lib/tradingdesk/room-tokens.env)
    meta.dialecticRoomToken      back-compat for a checkout that still has one
    DIALECTIC_ROOM_TOKEN         legacy single-room setups

WHY env wins over the book: after the scrub the books carry nothing, but a
stale checkout might — and if the two ever disagree, the operator's
environment is the one they can change without a commit.

WHY a file tier exists at all: a thesis created from Dialectic binds a NEW
room, and the pushing process resolves tokens from its own environment —
which cannot change without a service restart. The runtime file lives under
/var/lib/tradingdesk (outside the git tree, 0600), so registering a token
there via `register_room_token` makes the new room pushable on the next
cycle while preserving the invariant this module was born from: no live
credential ever sits in a tracked file. Env still wins on conflict — the
operator's environment remains the last word.

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
ENV_ROOM_TOKENS_FILE = "DIALECTIC_ROOM_TOKENS_FILE"
DEFAULT_ROOM_TOKENS_FILE = "/var/lib/tradingdesk/room-tokens.env"


def parse_room_tokens(raw: str, *, source: str = ENV_ROOM_TOKENS) -> dict:
    """Parse `uuid:token,uuid:token` into {canonical_uuid: token}.

    An empty or absent value yields {}, which simply means "no tokens
    configured here" — the caller then falls through to its other sources.
    `source` only labels the warnings, so a file-tier entry blames the file
    rather than the env var.
    """
    mapping: dict = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        raw_uuid, sep, token = pair.partition(":")
        if not sep or not token.strip():
            warnings.warn(
                f"{source}: skipping malformed entry (expected "
                f"uuid:token) for key {raw_uuid.strip()!r}",
                stacklevel=2,
            )
            continue
        try:
            key = str(_uuid.UUID(raw_uuid.strip()))
        except ValueError:
            warnings.warn(
                f"{source}: skipping entry with non-UUID key "
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


def _tokens_file_path(env: Mapping[str, str]) -> str:
    return (env.get(ENV_ROOM_TOKENS_FILE) or "").strip() or DEFAULT_ROOM_TOKENS_FILE


def load_file_tokens(env: Optional[Mapping[str, str]] = None) -> dict:
    """Tokens registered at runtime (see `register_room_token`), or {}.

    A missing or unreadable file is the normal state on a box where no
    thesis has ever been created from Dialectic — silence, not a warning.
    """
    env = os.environ if env is None else env
    path = _tokens_file_path(env)
    try:
        with open(path) as f:
            raw = f.read()
    except OSError:
        return {}
    # One pair per line in the file; parse_room_tokens speaks comma.
    return parse_room_tokens(",".join(raw.splitlines()), source=path)


def register_room_token(
    room_id: str, token: str, *, env: Optional[Mapping[str, str]] = None,
) -> str:
    """Persist `room_id: token` into the runtime token file; returns the path.

    Atomic (tmp + rename) and 0600 from the first byte — the file holds live
    credentials. Re-registering a room replaces its token, so a Dialectic-side
    rotation is one more call, not an edit. Raises ValueError on a non-UUID
    room id or an empty token; the caller owed us validated input.
    """
    env = os.environ if env is None else env
    canonical = _canonical(room_id)
    if not canonical:
        raise ValueError(f"room_id is not a UUID: {room_id!r}")
    token = (token or "").strip()
    if not token:
        raise ValueError("token must be non-empty")
    if ":" in token or "," in token or "\n" in token:
        # The file format's two delimiters and its line separator — a token
        # carrying one would corrupt every entry parsed after it.
        raise ValueError("token must not contain ':', ',' or newlines")

    mapping = load_file_tokens(env)
    mapping[canonical] = token
    path = _tokens_file_path(env)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(f"{k}:{v}" for k, v in sorted(mapping.items())) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def unregister_room_token(
    room_id: str, *, env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Drop a room's entry from the runtime token file; True if one existed.

    The retire flow calls this — a room that no longer has a thesis has no
    business holding a live push credential in the file. Env entries are
    the operator's and are never touched. An empty file is removed rather
    than left as a zero-entry credential file.
    """
    env = os.environ if env is None else env
    canonical = _canonical(room_id)
    if not canonical:
        return False
    mapping = load_file_tokens(env)
    if canonical not in mapping:
        return False
    del mapping[canonical]
    path = _tokens_file_path(env)
    if not mapping:
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(f"{k}:{v}" for k, v in sorted(mapping.items())) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return True


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
        token = load_file_tokens(env).get(room_id)
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
