# api/auth/schemas.py - Pydantic models for auth endpoints
"""
ARCHITECTURE: Request/response schemas for auth endpoints.
WHY: Type-safe validation with automatic OpenAPI documentation.
TRADEOFF: Some duplication with internal models for API boundary clarity.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class SignUpRequest(BaseModel):
    """Request body for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    display_name: str = Field(..., min_length=1, max_length=100)


class SignInRequest(BaseModel):
    """Request body for user login."""
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Request body for token refresh."""
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    """Request body for email verification."""
    code: str = Field(..., pattern=r"^\d{6}$", description="6-digit verification code")


class ForgotPasswordRequest(BaseModel):
    """Request body for forgot password."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request body for password reset."""
    email: EmailStr
    code: str = Field(..., pattern=r"^\d{6}$", description="6-digit reset code")
    new_password: str = Field(..., min_length=8, description="Minimum 8 characters")


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class TokenResponse(BaseModel):
    """Response containing auth tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: UUID


class UserResponse(BaseModel):
    """Response containing user information."""
    id: UUID
    email: str
    display_name: str
    email_verified: bool


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    detail: Optional[str] = None
