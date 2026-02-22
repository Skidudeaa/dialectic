# api/token_utils.py — Shared room token extraction for all routers

"""
ARCHITECTURE: Centralized token extraction supporting query param + Authorization header.
WHY: React frontend sends tokens via header; legacy clients use query params.
TRADEOFF: Single shared dependency vs duplicated extraction logic per router.
"""

from typing import Optional
from fastapi import Query, Header, HTTPException


def extract_room_token(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    Extract room token from query param OR Authorization header.
    Prefers Authorization header (more secure — not logged by proxies).
    Falls back to query param for backward compatibility.
    """
    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization

    if token:
        return token

    raise HTTPException(
        status_code=401,
        detail="Room token required (query param or Authorization header)"
    )
