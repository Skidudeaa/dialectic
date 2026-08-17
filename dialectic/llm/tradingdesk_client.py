# llm/tradingdesk_client.py — authenticated read-only client for tradingDesk

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_BASE_URL = "http://127.0.0.1:8006"

# The timeout law of the seam, in ONE place: a proxy budget must EXCEED the
# inner fetch's own, or a graceful slow answer arrives as a failure.
#
# `/api/bridge/news/{book}` now makes one bounded 20s GDELT attempt; source-wide
# cooldown replaces sleeping and retrying inside a human turn. The HTTP client
# gets five seconds to receive and decode that answer before the 29s tool guard.
NEWS_TIMEOUT_S = 25.0

# The bridge reads every configured Polymarket ID concurrently. Each ID gets
# two attempts; an attempt can make two sequential 5s requests, with a 1.5s
# retry delay. 25s clears that 21.5s cold ceiling inside the LLM's 60s turn.
POLYMARKET_TIMEOUT_S = 25.0


class TradingDeskError(Exception):
    """Any failure talking to tradingDesk — unreachable, non-200, non-JSON,
    timeout, or a login that could not produce a token.

    WHY one exception type: the tool loop turns every failure into the same
    is_error tool_result telling the model the check failed. Callers never
    branch on the reason, so a taxonomy would be dead structure — the reason
    lives in the message, where the model can read it.
    """


# WHY module-level: an httpx.AsyncClient owns a connection pool. The registry
# is rebuilt per WebSocket message, so a per-call client would open (and leak)
# a pool on every tool invocation. Mirrors _provider_cache in providers.py.
_client: Optional[httpx.AsyncClient] = None
_token: Optional[str] = None
_login_lock: Optional[asyncio.Lock] = None


def _base_url() -> str:
    """Read the env at CALL time — run.py loads .env after import."""
    return os.environ.get("TRADINGDESK_URL", DEFAULT_BASE_URL).rstrip("/")


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
    return _client


def _get_lock() -> asyncio.Lock:
    # Created lazily so importing this module never touches an event loop.
    global _login_lock
    if _login_lock is None:
        _login_lock = asyncio.Lock()
    return _login_lock


def reset() -> None:
    """Drop the cached client and token.

    Used by tests (which install an httpx.MockTransport client) and available
    for credential rotation. Does not await close() — the caller owns that.
    """
    global _client, _token
    _client = None
    _token = None


def _require_json(response: httpx.Response, what: str) -> Any:
    """Status + content-type + parse, in that order.

    WHY the content-type check: tradingDesk's SPA catch-all answers unknown
    paths with 200 + text/html. Status alone would read a React shell as a
    successful API call and hand the model an HTML string as live data.
    """
    if response.status_code != 200:
        raise TradingDeskError(
            f"{what} returned HTTP {response.status_code}"
        )
    ctype = response.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        raise TradingDeskError(
            f"{what} returned {ctype or 'no content-type'}, not JSON "
            f"(the endpoint probably does not exist)"
        )
    try:
        return response.json()
    except ValueError as e:
        raise TradingDeskError(f"{what} returned unparseable JSON: {e}")


async def _login() -> str:
    """Exchange the service credential for a JWT (valid ~72h)."""
    user = os.environ.get("TRADINGDESK_USER")
    password = os.environ.get("TRADINGDESK_PASSWORD")
    if not user or not password:
        raise TradingDeskError(
            "TRADINGDESK_USER/TRADINGDESK_PASSWORD are not set — "
            "tradingDesk tools are unavailable"
        )

    client = _get_client()
    try:
        response = await client.post(
            f"{_base_url()}/api/auth/login",
            json={"username": user, "password": password},
        )
    except httpx.HTTPError as e:
        raise TradingDeskError(f"tradingDesk login unreachable: {type(e).__name__}: {e}")

    data = _require_json(response, "tradingDesk login")
    token = (data or {}).get("access_token")
    if not token:
        raise TradingDeskError("tradingDesk login returned no access_token")
    logger.info("tradingDesk login succeeded for user=%s", user)
    return token


async def _token_value(force: bool = False) -> str:
    global _token
    lock = _get_lock()
    async with lock:
        if force or not _token:
            _token = await _login()
        return _token


async def request_json(
    method: str,
    path: str,
    *,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Authenticated request returning parsed JSON.

    Re-logins exactly ONCE on a 401 (the JWT expired mid-session) and re-raises
    if the retry is refused too — a second 401 means the credential itself is
    wrong, and retrying a wrong password in a loop helps nobody.
    """
    client = _get_client()
    url = f"{_base_url()}{path}"
    token = await _token_value()

    async def _send(bearer: str) -> httpx.Response:
        try:
            return await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                json=json_body,
                params=params,
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT_S,
            )
        except httpx.TimeoutException as e:
            raise TradingDeskError(f"tradingDesk {path} timed out: {e}")
        except httpx.HTTPError as e:
            raise TradingDeskError(
                f"tradingDesk {path} unreachable: {type(e).__name__}: {e}"
            )

    response = await _send(token)
    if response.status_code == 401:
        logger.info("tradingDesk 401 on %s — re-logging in once", path)
        token = await _token_value(force=True)
        response = await _send(token)

    return _require_json(response, f"tradingDesk {path}")


async def service_get(
    path: str,
    *,
    params: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Service-token GET for the /api/bridge/* endpoints (X-Service-Token,
    not the user JWT everything else here carries).

    WHY a separate path: the bridge endpoints gate on TD_SERVICE_TOKEN
    service-to-service auth (mirrors trading_watch.trading_reconcile), and
    re-login-on-401 makes no sense against a static token. A non-JSON 200
    still trips the SPA guard in _require_json, so an unshipped endpoint
    surfaces as TradingDeskError("...not JSON..."), never as HTML "data".
    """
    token = os.environ.get("TD_SERVICE_TOKEN", "")
    if not token:
        raise TradingDeskError(
            "TD_SERVICE_TOKEN is not set — tradingDesk bridge endpoints "
            "are unavailable"
        )
    client = _get_client()
    try:
        response = await client.get(
            f"{_base_url()}{path}",
            headers={"X-Service-Token": token},
            params=params,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT_S,
        )
    except httpx.TimeoutException as e:
        raise TradingDeskError(f"tradingDesk {path} timed out: {e}")
    except httpx.HTTPError as e:
        raise TradingDeskError(
            f"tradingDesk {path} unreachable: {type(e).__name__}: {e}"
        )
    return _require_json(response, f"tradingDesk {path}")


async def service_post(
    path: str, *, json_body: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Service-token POST — same contract as service_get, for the one
    bridge write (room-token registration). Static token, no re-login."""
    token = os.environ.get("TD_SERVICE_TOKEN", "")
    if not token:
        raise TradingDeskError(
            "TD_SERVICE_TOKEN is not set — tradingDesk bridge endpoints "
            "are unavailable"
        )
    client = _get_client()
    try:
        response = await client.post(
            f"{_base_url()}{path}",
            json=json_body,
            headers={"X-Service-Token": token},
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT_S,
        )
    except httpx.TimeoutException as e:
        raise TradingDeskError(f"tradingDesk {path} timed out: {e}")
    except httpx.HTTPError as e:
        raise TradingDeskError(
            f"tradingDesk {path} unreachable: {type(e).__name__}: {e}"
        )
    return _require_json(response, f"tradingDesk {path}")


async def get(path: str, *, params: Optional[dict] = None,
              timeout: Optional[float] = None) -> Any:
    return await request_json("GET", path, params=params, timeout=timeout)


async def post(path: str, *, json_body: Optional[dict] = None,
               params: Optional[dict] = None,
               timeout: Optional[float] = None) -> Any:
    return await request_json("POST", path, json_body=json_body,
                              params=params, timeout=timeout)


async def run_command(command_id: str, args: Optional[dict] = None,
                      *, timeout: Optional[float] = None) -> Any:
    """Dispatch a registry command and unwrap its envelope.

    tradingDesk answers /api/v1/commands/{id} with
    {"command_id", "ok": true, "result": ...}. Callers want the result.
    """
    envelope = await post(
        f"/api/v1/commands/{command_id}",
        json_body=args or {},
        timeout=timeout,
    )
    if not isinstance(envelope, dict):
        raise TradingDeskError(
            f"command {command_id} returned {type(envelope).__name__}, expected an object"
        )
    if envelope.get("ok") is False:
        raise TradingDeskError(f"command {command_id} reported failure: {envelope}")
    return envelope.get("result")
