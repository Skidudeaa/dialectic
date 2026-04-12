"""
FastAPI dependency injection helpers.

WHY: Routes need access to the Repository instance stored on app.state.
A dependency function is cleaner than importing app and accessing .state
directly, and it's overridable in tests via app.dependency_overrides.
"""

from fastapi import Depends, Request

from web.persistence.repository import Repository


def get_repo(request: Request) -> Repository:
    """Get the Repository instance from app state.

    WHY: Stored on app.state during lifespan init. Routes declare this
    as a dependency: `repo: Repository = Depends(get_repo)`.
    """
    return request.app.state.repo
