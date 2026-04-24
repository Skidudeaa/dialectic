"""
Command registry HTTP surface — GET catalog + POST dispatch.

WHY: The Ctrl+K palette and LLM tool-use share one registry. The LLM
introspects via GET to learn what it can do; the palette POSTs the handler
with validated args.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from web.auth import get_current_user
from web.runtime import command_registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1", "commands"])


@router.get("/commands")
async def get_commands(_user=Depends(get_current_user)) -> Dict[str, Any]:
    """Return the full catalog of registered commands."""
    return {"commands": command_registry.list_commands()}


@router.post("/commands/{command_id}")
async def dispatch_command(
    command_id: str,
    request: Request,
    _user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Validate the request body against the command schema and dispatch.

    * 404 when the id is unknown.
    * 400 when the body fails schema validation.
    * 500 (bubbled from FastAPI) when the handler raises unexpectedly.
    """
    cmd = command_registry.get(command_id)
    if cmd is None:
        raise HTTPException(status_code=404, detail=f"Unknown command: {command_id}")

    # Body is optional for commands with no required fields.
    try:
        body_raw = await request.body()
        if body_raw:
            body = await request.json()
        else:
            body = {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    # Validate against the command's JSON-Schema. Draft202012Validator matches
    # the output of Pydantic's model_json_schema.
    try:
        validator = Draft202012Validator(cmd.input_schema)
        errors = sorted(validator.iter_errors(body), key=lambda e: e.path)
    except Exception as exc:  # malformed schema — server bug, not client
        log.error("Command %s has an invalid schema: %s", command_id, exc)
        raise HTTPException(status_code=500, detail="Command schema is invalid")

    if errors:
        formatted = []
        for err in errors:
            path = ".".join(str(p) for p in err.absolute_path) or "<root>"
            formatted.append({"field": path, "message": err.message})
        raise HTTPException(
            status_code=400,
            detail={"command_id": command_id, "validation_errors": formatted},
        )

    try:
        result = await cmd.handler(body)
    except HTTPException:
        raise
    except ValidationError as exc:  # pragma: no cover — double-check safety net
        raise HTTPException(status_code=400, detail=str(exc))
    except (FileNotFoundError, ValueError) as exc:
        # Handlers surface these for known bad inputs (unknown book id etc.).
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("Command %s handler failed", command_id)
        raise HTTPException(status_code=500, detail=f"Command failed: {exc}")

    return {
        "command_id": command_id,
        "ok": True,
        "result": result,
    }
