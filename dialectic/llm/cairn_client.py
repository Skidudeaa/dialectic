# llm/cairn_client.py — read-only client for the local cairn dev-memory backend

import os
from typing import Any, Optional

import httpx

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_BASE_URL = "http://127.0.0.1:9000"


class CairnError(Exception):
    """Any failure talking to the cairn backend — unreachable, non-200,
    non-JSON, or a timeout.

    WHY one exception type: mirrors DefuddleError/TradingDeskError. The tool
    loop turns every failure into the same is_error tool_result, so callers
    never branch on the reason — it lives in the message, where the model
    can read it.
    """


# WHY module-level: an httpx.AsyncClient owns a connection pool. The registry
# is rebuilt per WebSocket message, so a per-call client would open (and leak)
# a pool on every tool invocation. Mirrors defuddle_client._client.
_client: Optional[httpx.AsyncClient] = None


def _base_url() -> str:
    """Read the env at CALL time — run.py loads .env after import."""
    return os.environ.get("CAIRN_URL", DEFAULT_BASE_URL).rstrip("/")


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


def _require_json(response: httpx.Response) -> Any:
    """Status → content-type → parse, in that order.

    The content-type check is the SPA guard: a proxy or wrong port can
    return an HTML shell with a 200, and json() on that raises far from
    the cause.
    """
    if response.status_code != 200:
        # FastAPI error bodies carry {"detail": ...} — surface it so the
        # model can report the actual reason.
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("detail", ""))
        except ValueError:
            pass
        raise CairnError(
            f"dev memory returned HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
        )

    ctype = response.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        raise CairnError(
            f"dev memory returned {ctype or 'no content-type'}, not JSON"
        )
    try:
        return response.json()
    except ValueError as e:
        raise CairnError(f"dev memory returned unparseable JSON: {e}")


async def get(path: str, *, params: Optional[dict] = None,
              timeout: float = DEFAULT_TIMEOUT_S) -> Any:
    """GET a cairn endpoint and return the parsed JSON payload.

    No auth: cairn is single-user on this host and binds loopback only —
    that binding is the trust boundary.
    """
    client = _get_client()
    try:
        response = await client.get(
            f"{_base_url()}{path}", params=params, timeout=timeout,
        )
    except httpx.TimeoutException as e:
        raise CairnError(f"dev memory timed out: {e}")
    except httpx.HTTPError as e:
        raise CairnError(f"dev memory unreachable: {type(e).__name__}: {e}")
    return _require_json(response)


async def post(path: str, *, json: Optional[dict] = None,
               timeout: float = DEFAULT_TIMEOUT_S) -> Any:
    """POST to a cairn endpoint (search endpoints are POST-shaped reads)."""
    client = _get_client()
    try:
        response = await client.post(
            f"{_base_url()}{path}", json=json, timeout=timeout,
        )
    except httpx.TimeoutException as e:
        raise CairnError(f"dev memory timed out: {e}")
    except httpx.HTTPError as e:
        raise CairnError(f"dev memory unreachable: {type(e).__name__}: {e}")
    return _require_json(response)
