"""
HMAC / timestamp / nonce verification for TradingView Pine Script webhooks.

WHY a dedicated module (not inlined in the FastAPI route): these functions are
the security perimeter of the webhook. Keeping them pure (no FastAPI imports,
no I/O) makes them directly unit-testable without spinning up a TestClient,
and keeps the route file focused on HTTP plumbing.

Security posture (mirrors the Alpha v2 plan):
- HMAC-SHA256 with hmac.compare_digest (constant-time comparison).
- ±300s timestamp window via X-TV-Timestamp header (410 on violation).
- Nonce replay protection via in-process dict with 10-min TTL (409 on
  replay). Single-worker deployment — see VerifyResult.NONCE_REPLAY.
- Path resolution + startswith check on book IDs (done by the route, not
  here) combined with regex validation to block traversal.
- 8 KiB body cap enforced upstream by FastAPI request size limit.

This module is stdlib only (hmac, hashlib, threading, time). Zero pip deps.
"""
from __future__ import annotations

import hmac
import hashlib
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ── Configuration ─────────────────────────────────────────────────────────

# ±300 seconds (5 minutes) is the same window Stripe and GitHub webhooks use.
# Wider would accept stale replays; narrower rejects legitimate alerts when
# clocks drift on consumer-grade hardware.
DEFAULT_CLOCK_SKEW_SECONDS = 300

# 10-minute nonce TTL balances memory against protection: within the 5-min
# timestamp window an attacker cannot replay, and after 10 minutes the nonce
# is pruned. A longer TTL would grow memory unbounded under attack; shorter
# would allow replays across the timestamp window.
DEFAULT_NONCE_TTL_SECONDS = 600

# Minimum nonce length. 8 bytes = 64 bits of entropy assuming random hex;
# enough to make collisions astronomically unlikely in the 600s TTL window.
MIN_NONCE_LENGTH = 8


# ── Verification result codes ─────────────────────────────────────────────

class VerifyResult(str, Enum):
    """Structured verification outcomes.

    Mapped to HTTP codes by the route handler:
      OK              → 200 (proceed with mutation)
      NO_SECRET       → 500 (misconfigured — the env var TV_WEBHOOK_SECRET is unset)
      BAD_SIGNATURE   → 401 (HMAC mismatch)
      BAD_TIMESTAMP   → 410 (header missing/non-numeric/outside ±skew window)
      BAD_NONCE       → 400 (nonce missing or too short)
      NONCE_REPLAY    → 409 (nonce seen within TTL)
    """
    OK = "ok"
    NO_SECRET = "no_secret"
    BAD_SIGNATURE = "bad_signature"
    BAD_TIMESTAMP = "bad_timestamp"
    BAD_NONCE = "bad_nonce"
    NONCE_REPLAY = "nonce_replay"


@dataclass
class VerificationContext:
    """Input bundle for verify_request — all headers + body the route already has."""
    body: bytes
    signature_header: str
    timestamp_header: str
    nonce_header: str
    secret: Optional[str]


# ── Pure verification functions ───────────────────────────────────────────

def verify_signature(body: bytes, provided_header: str, secret: bytes) -> bool:
    """Constant-time HMAC-SHA256 signature check.

    Expected header shape: ``sha256=<hex>``. Any other format returns False.
    """
    if not provided_header or not isinstance(provided_header, str):
        return False
    if not provided_header.startswith("sha256="):
        return False
    expected_hex = hmac.new(secret, body, hashlib.sha256).hexdigest()
    expected = "sha256=" + expected_hex
    # compare_digest is constant-time against length-matched inputs.
    return hmac.compare_digest(expected, provided_header)


def verify_timestamp(header_value: str, now_seconds: float,
                     skew: int = DEFAULT_CLOCK_SKEW_SECONDS) -> bool:
    """Validate X-TV-Timestamp against ``now`` within a ±skew window.

    Non-integer headers return False. A zero/negative timestamp fails the
    window check on realistic clocks.
    """
    if not header_value:
        return False
    try:
        ts = int(header_value)
    except (TypeError, ValueError):
        return False
    return abs(now_seconds - ts) <= skew


def canonical_signing_string(timestamp_header: str, nonce_header: str,
                              body: bytes) -> bytes:
    """Build the canonical signing bytes: ``timestamp.nonce.body``.

    WHY ts and nonce are inside the MAC: signing the raw body alone lets an
    attacker who has captured one legitimate signed request replay the exact
    (body, signature) pair indefinitely with a fresh timestamp + fresh nonce.
    Both headers are unauthenticated under body-only signing. Folding them
    into the HMAC binds the signature to a specific moment in time + a
    specific nonce, so the ±300s window and nonce store become meaningful.

    The encoding is stable: UTF-8 for the two headers, raw bytes for the
    body. The ``.`` separator is outside any header's allowed charset
    (digits for ts, hex for nonce), so no collision is possible.
    """
    return b".".join([
        timestamp_header.encode(),
        nonce_header.encode(),
        body,
    ])


def sign_canonical(timestamp_header: str, nonce_header: str,
                   body: bytes, secret: str) -> str:
    """Produce the X-TV-Signature value covering ts + nonce + body.

    This is the helper relays (``tools/bridge/sign_tv_alert.py``) and tests
    use. Pair with :func:`verify_request` which computes the same canonical
    bytes before calling :func:`verify_signature`.
    """
    canonical = canonical_signing_string(timestamp_header, nonce_header, body)
    return sign_body(canonical, secret)


# ── Nonce store ───────────────────────────────────────────────────────────

class NonceStore:
    """Thread-safe in-process nonce tracker with TTL-based pruning.

    WHY in-process (not Redis): the deployment target is a single uvicorn
    worker inside docker-compose. A Redis dependency would be the first pip
    install in the project's history. If the app ever scales to multiple
    workers, this class becomes the single line to swap — keep the public
    surface small (seen / purge / clear / __len__).

    Memory envelope: at worst the store holds (600s / min_alert_interval)
    entries. With a 1-second rate limit that's 600 entries per IP, sized at
    ~120 bytes per dict entry = ~72 KB per attacker. Tolerable.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_NONCE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, float] = {}  # nonce → expires_at

    def _purge_expired_locked(self, now: float) -> None:
        """Prune stale nonces. Caller must hold self._lock."""
        expired = [k for k, exp in self._entries.items() if exp < now]
        for k in expired:
            self._entries.pop(k, None)

    def seen(self, nonce: str, now: Optional[float] = None) -> bool:
        """Return True if this nonce has been seen within TTL (replay).

        Registers the nonce as seen on the ``not seen`` branch. Safe for
        concurrent calls — atomic under the lock.
        """
        if now is None:
            now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            if nonce in self._entries:
                return True
            self._entries[nonce] = now + self._ttl
            return False

    def clear(self) -> None:
        """Reset the store — used by tests between cases."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# Module-level singleton — the route imports this directly. Tests can reset
# via ``.clear()`` in an autouse fixture.
nonce_store = NonceStore()


# ── High-level verification entry point ───────────────────────────────────

def verify_request(
    ctx: VerificationContext,
    *,
    now_seconds: Optional[float] = None,
    skew: int = DEFAULT_CLOCK_SKEW_SECONDS,
    store: Optional[NonceStore] = None,
) -> VerifyResult:
    """Run the full verification chain in order.

    Order matters: cheapest / safest rejections first, then the HMAC
    (which costs a hash compute), then the nonce (which mutates state).
    This prevents attackers from burning the nonce store with bad requests.
    """
    if not ctx.secret:
        return VerifyResult.NO_SECRET

    # Timestamp first — cheapest, protects against replay of very old
    # messages even if the attacker has the secret.
    if now_seconds is None:
        now_seconds = time.time()
    if not verify_timestamp(ctx.timestamp_header, now_seconds, skew=skew):
        return VerifyResult.BAD_TIMESTAMP

    # Nonce format next — rejects empty/short nonces before HMAC compute.
    if not ctx.nonce_header or len(ctx.nonce_header) < MIN_NONCE_LENGTH:
        return VerifyResult.BAD_NONCE

    # HMAC — constant-time, single hash compute.
    # WHY sign the canonical string (ts+nonce+body), not body alone: body-only
    # signing lets a captured request be replayed forever with fresh ts+nonce
    # headers, because those headers are attacker-controlled and outside the
    # MAC. See canonical_signing_string docstring for the threat model.
    secret_bytes = ctx.secret.encode() if isinstance(ctx.secret, str) else ctx.secret
    canonical = canonical_signing_string(
        ctx.timestamp_header, ctx.nonce_header, ctx.body,
    )
    if not verify_signature(canonical, ctx.signature_header, secret_bytes):
        return VerifyResult.BAD_SIGNATURE

    # Only register the nonce after signature is valid. This prevents an
    # attacker with forged signatures from exhausting the nonce store.
    ns = store if store is not None else nonce_store
    if ns.seen(ctx.nonce_header, now=now_seconds):
        return VerifyResult.NONCE_REPLAY

    return VerifyResult.OK


# ── Signing helper (test fixtures only) ───────────────────────────────────

def sign_body(body: bytes, secret: str) -> str:
    """Produce ``sha256=<hex>`` over raw bytes.

    Low-level primitive paired with :func:`verify_signature`. For HTTP
    webhook signing, prefer :func:`sign_canonical` which covers timestamp
    and nonce — body-only signatures are vulnerable to header-swap replay.
    """
    secret_bytes = secret.encode() if isinstance(secret, str) else secret
    digest = hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
