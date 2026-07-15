# api/token_utils.py — Shared room token extraction for all routers

"""
ARCHITECTURE: Centralized token extraction supporting a dedicated header plus legacy fallbacks.
WHY: React frontend sends tokens via header; legacy clients use query params.
TRADEOFF: Single shared dependency vs duplicated extraction logic per router.
"""

from typing import Optional
from fastapi import Query, Header, HTTPException


def extract_room_token(
    token: Optional[str] = Query(None),
    x_room_token: Optional[str] = Header(None, alias="X-Room-Token"),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    Extract a room token without competing with the user's JWT.

    WHY: Authenticated clients need two credentials at once: the user JWT in
    Authorization and the room invite capability in X-Room-Token. Keeping them
    separate avoids room secrets in URLs and prevents a JWT from being mistaken
    for a room token.

    Query and Authorization remain compatibility fallbacks for legacy/native
    clients and the trading bridge. New browser clients use X-Room-Token.
    """
    if x_room_token:
        return x_room_token

    if token:
        return token

    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization

    raise HTTPException(
        status_code=401,
        detail="Room token required"
    )
