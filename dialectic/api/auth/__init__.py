# api/auth/__init__.py - Authentication module
"""
ARCHITECTURE: Modular auth package with clear separation of concerns.
WHY: Keeps auth logic isolated from main API, easier to test and maintain.
TRADEOFF: More files to navigate vs cleaner organization.
"""

from .routes import router

__all__ = ["router"]
