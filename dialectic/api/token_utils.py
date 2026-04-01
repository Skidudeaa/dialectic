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

    WHY: Explicit query param takes precedence over the Authorization header.
    When a JWT-authenticated frontend also sends a room token, both are present
    simultaneously. The query param carries the room token; the Authorization
    header carries the user JWT. Preferring the query param avoids the JWT being
    misinterpreted as a room token, which caused 401s for authenticated users.

    Authorization header is still accepted as a fallback for clients that send
    the room token there directly (e.g. push-to-dialectic.py bridge script).
    """
    if token:
        return token

    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization

    raise HTTPException(
        status_code=401,
        detail="Room token required (query param or Authorization header)"
    )
