"""Structured logging + readiness observability for the runtime.

WHY: v2 Unit 14. The coordinator emits log lines during every evaluation
cycle, and operators need to answer: which thesis? which revision? how long
did it take? The JSON formatter here turns that into machine-parseable
output, and the thesis_context helper pushes per-cycle fields into the
log record via contextvars.
"""
from web.observability.logging import (
    JsonFormatter,
    configure_structured_logging,
    thesis_context,
)

__all__ = ["JsonFormatter", "configure_structured_logging", "thesis_context"]
