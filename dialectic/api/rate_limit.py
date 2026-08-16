"""Fixed authentication rate limits for the single-process deployment."""

import hashlib
import time
from collections.abc import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    """Keep bounded timestamp buckets for fixed-window request policies."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record one request and return whether it fits the requested policy."""
        now = self._clock()
        stale_cutoff = now - 3600
        for known_key, timestamps in tuple(self._requests.items()):
            if not timestamps or timestamps[-1] <= stale_cutoff:
                del self._requests[known_key]

        cutoff = now - window_seconds
        bucket = [stamp for stamp in self._requests.get(key, []) if stamp > cutoff]
        self._requests[key] = bucket
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


rate_limiter = RateLimiter()


def _client_ip(request: Request) -> str:
    """Return the direct peer address used by the existing deployment policy."""
    return request.client.host if request.client else "unknown"


def _reject_if_limited(key: str, limit: int, window_seconds: int) -> None:
    if not rate_limiter.is_allowed(key, limit, window_seconds):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )


def check_rate_limit(request: Request) -> None:
    """Enforce the fixed global auth-router policy of 60 requests per minute."""
    _reject_if_limited(
        f"ip:{_client_ip(request)}:{request.url.path}",
        60,
        60,
    )


def check_ip_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Enforce a route policy using only the caller's peer address."""
    _reject_if_limited(
        f"ip:{_client_ip(request)}:{scope}",
        limit,
        window_seconds,
    )


def check_account_rate_limit(
    request: Request,
    account_identifier: str,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Enforce matching IP and privacy-preserving account rate limits."""
    normalized = account_identifier.strip().lower().encode()
    account_digest = hashlib.sha256(normalized).hexdigest()
    check_ip_rate_limit(
        request,
        scope=scope,
        limit=limit,
        window_seconds=window_seconds,
    )
    _reject_if_limited(
        f"account:{account_digest}:{scope}",
        limit,
        window_seconds,
    )
