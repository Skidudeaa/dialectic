"""
Reusable confirm-token machinery for destructive routes.

WHY: Multiple routes (trade kill, scenario override apply, builder delete)
all need the same two-step "issue token → consume token" flow. Instead of
duplicating the token map per route, the persisted ``confirm_tokens``
table from migration 002 is the single source of truth, and these helpers
are the public API every route uses.

Usage in a route::

    @router.post("/dangerous/{target_id}")
    async def dangerous(
        target_id: str,
        req: SomeRequest,
        user=Depends(get_current_user),
        repo=Depends(get_repo),
    ):
        if req.confirm_token is None:
            return request_confirm_token(repo, user.username, "scope.action", target_id)
        require_confirm_token(repo, req.confirm_token, user.username, "scope.action", target_id)
        # ... do the destructive work, then ...
        repo.add_audit_row(user.username, "scope.action", target_id,
                           reason=req.reason, confirm_token=req.confirm_token)
"""

import asyncio
from typing import Any, Dict

from fastapi import HTTPException

from web.persistence.repository import Repository


CONFIRM_TTL_SECONDS = 30


def request_confirm_token(repo: Repository, actor: str, action: str,
                          target: str,
                          ttl_seconds: int = CONFIRM_TTL_SECONDS) -> Dict[str, Any]:
    """Issue a fresh confirm token and return the response shape routes use.

    WHY this shape: matches the dict Unit 10's kill route raised inside an
    HTTPException(409) detail — keeps the wire contract identical so the
    frontend's existing modal handler doesn't need to change.
    """
    record = repo.issue_confirm_token(actor, action, target,
                                      ttl_seconds=ttl_seconds)
    return {
        "confirm_required": True,
        "confirm_token": record["token"],
        "expires_at": record["expires_at"],
        "ttl_seconds": int(ttl_seconds),
        "action": action,
        "target": target,
    }


async def request_confirm_token_async(repo: Repository, actor: str, action: str,
                                      target: str,
                                      ttl_seconds: int = CONFIRM_TTL_SECONDS) -> Dict[str, Any]:
    """Async wrapper — repo work runs on the thread pool to avoid blocking the loop."""
    return await asyncio.to_thread(
        request_confirm_token, repo, actor, action, target, ttl_seconds,
    )


def require_confirm_token(repo: Repository, token: str, actor: str,
                          action: str, target: str) -> None:
    """Verify and consume a confirm token. Raise 409 on failure.

    WHY 409: the request is well-formed but the prerequisite (a valid,
    matching, unconsumed token) is missing — same status the legacy
    flow returned for "first call, no token yet".
    """
    if not token:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "confirm_token_required",
                "action": action,
                "target": target,
            },
        )
    ok = repo.consume_confirm_token(token, actor, action, target)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "confirm_token_invalid",
                "action": action,
                "target": target,
            },
        )


async def require_confirm_token_async(repo: Repository, token: str, actor: str,
                                      action: str, target: str) -> None:
    """Async wrapper — verifies via thread pool."""
    await asyncio.to_thread(
        require_confirm_token, repo, token, actor, action, target,
    )
