"""Structured JSON log formatter + thesis-context helper.

WHY a dedicated module: the coordinator and scheduler run lots of per-thesis
cycles and we want every log line from inside those cycles tagged with
`thesisId`, `revision`, and `runId`. contextvars propagates those fields
across asyncio.to_thread and asyncio.gather without requiring every log
call to pass them explicitly.

The formatter emits JSONL output — one JSON object per line — with a stable
key order (timestamp, level, name, message, then context fields, then
extras). This matches what `jq`, `grep -P`, and typical log shippers
expect.
"""
from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional


# Context fields propagated across awaits. None = not set → omitted from log.
_thesis_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "thesis_id", default=None,
)
_revision: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "revision", default=None,
)
_run_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "run_id", default=None,
)


# Standard logging-record attributes we intentionally skip when we dump the
# extras bucket — they're already in top-level fields or are implementation
# detail that would bloat the log line.
_RESERVED_RECORD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class JsonFormatter(logging.Formatter):
    """JSONL formatter with stable key order + thesis context fields.

    Output shape:
        {"ts": "2026-04-21T...", "level": "INFO", "name": "web.runtime...",
         "message": "tick cycle complete", "thesisId": "iran-hormuz-graph",
         "revision": 42, "runId": 317, "durationMs": 184, "status": "ok"}

    Fields beyond the core set come from `extra={}` on the logging call and
    from any attributes attached via LogRecord subclassing. Context vars
    (thesis_id, revision, run_id) are always injected when set.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        tid = _thesis_id.get()
        if tid is not None:
            payload["thesisId"] = tid
        rev = _revision.get()
        if rev is not None:
            payload["revision"] = rev
        rid = _run_id.get()
        if rid is not None:
            payload["runId"] = rid

        # Extras — anything passed via `logger.info(..., extra={"durationMs": 12})`.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key in payload:
                continue
            if key.startswith("_"):
                continue
            # Only include JSON-serializable primitives; otherwise coerce to str
            # so a badly-typed extra never breaks the log pipeline.
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), default=str)


@contextmanager
def thesis_context(
    thesis_id: str,
    revision: Optional[int] = None,
    run_id: Optional[int] = None,
) -> Iterator[None]:
    """Push per-thesis context onto the current async task's log context.

    Usage:
        with thesis_context("iran-hormuz-graph", revision=42, run_id=317):
            log.info("tick cycle starting")
            await self._run_cycle(...)

    All log lines emitted inside the block — including from nested awaits,
    asyncio.to_thread calls, and library code using `logging.getLogger` —
    get the thesisId/revision/runId fields injected by JsonFormatter.
    """
    t_tok = _thesis_id.set(thesis_id)
    r_tok = _revision.set(revision) if revision is not None else None
    rid_tok = _run_id.set(run_id) if run_id is not None else None
    try:
        yield
    finally:
        _thesis_id.reset(t_tok)
        if r_tok is not None:
            _revision.reset(r_tok)
        if rid_tok is not None:
            _run_id.reset(rid_tok)


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Replace the root logger's handlers with a JSON-formatted stream handler.

    Idempotent — calling twice only leaves one JSON handler attached. Called
    once during FastAPI lifespan startup.
    """
    root = logging.getLogger()
    # Drop any pre-existing handlers (uvicorn installs its own default).
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
