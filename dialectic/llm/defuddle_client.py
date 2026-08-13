# llm/defuddle_client.py — read-only client for the local defuddle sidecar

import os
from typing import Any, Optional

import httpx

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_BASE_URL = "http://127.0.0.1:8010"


class DefuddleError(Exception):
    """Any failure talking to the defuddle sidecar — unreachable, non-200,
    non-JSON, or a timeout.

    WHY one exception type: mirrors TradingDeskError. The tool loop turns
    every failure into the same is_error tool_result, so callers never branch
    on the reason — it lives in the message, where the model can read it.
    """


# WHY module-level: an httpx.AsyncClient owns a connection pool. The registry
# is rebuilt per WebSocket message, so a per-call client would open (and leak)
# a pool on every tool invocation. Mirrors tradingdesk_client._client.
_client: Optional[httpx.AsyncClient] = None


def _base_url() -> str:
    """Read the env at CALL time — run.py loads .env after import."""
    return os.environ.get("DEFUDDLE_URL", DEFAULT_BASE_URL).rstrip("/")


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
    return _client


def reset() -> None:
    """Drop the cached client.

    Used by tests (which install an httpx.MockTransport client). Does not
    await close() — the caller owns that.
    """
    global _client
    _client = None


async def extract_article(url: str) -> Any:
    """POST /extract to the sidecar and return the parsed article payload.

    No auth: the sidecar binds loopback only, and its own input validation
    (http(s) only, no private/loopback targets) is the trust boundary.
    """
    client = _get_client()
    try:
        response = await client.post(
            f"{_base_url()}/extract",
            json={"url": url},
            timeout=DEFAULT_TIMEOUT_S,
        )
    except httpx.TimeoutException as e:
        raise DefuddleError(f"article extractor timed out: {e}")
    except httpx.HTTPError as e:
        raise DefuddleError(
            f"article extractor unreachable: {type(e).__name__}: {e}"
        )

    if response.status_code != 200:
        # The sidecar's error body carries the why ("upstream returned HTTP
        # 403") — surface it so the model can report the actual reason.
        detail = ""
        try:
            detail = (response.json() or {}).get("error", "")
        except ValueError:
            pass
        raise DefuddleError(
            f"article extractor returned HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
        )

    ctype = response.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        raise DefuddleError(
            f"article extractor returned {ctype or 'no content-type'}, not JSON"
        )
    try:
        return response.json()
    except ValueError as e:
        raise DefuddleError(f"article extractor returned unparseable JSON: {e}")
