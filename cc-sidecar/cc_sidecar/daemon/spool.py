"""
Spool file management: fallback persistence when the daemon is unavailable.

ARCHITECTURE: Per-session spool files in $XDG_RUNTIME_DIR/cc-sidecar/spool/.
WHY: When the daemon is down, events must not be lost. The emit CLI
appends to spool files that the daemon replays on next startup.
TRADEOFF: Best-effort persistence (no fdatasync) — losing one event
on machine crash is acceptable for observability data.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator

from cc_sidecar.constants import SPOOL_DIR, DIR_MODE

logger = logging.getLogger(__name__)


def get_spool_files() -> list[Path]:
    """
    List all spool files, sorted by modification time (oldest first).

    WHY: Process oldest events first to maintain causal ordering.
    """
    if not SPOOL_DIR.exists():
        return []
    files = sorted(SPOOL_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files


async def replay_spool_files() -> AsyncIterator[str]:
    """
    Yield event JSON lines from all spool files, sorted by mono_seq.

    After yielding all events from a file, the file is truncated.
    WHY: Sorting by mono_seq ensures correct causal ordering even when
    events were written by different processes to different spool files.
    """
    spool_files = get_spool_files()
    if not spool_files:
        return

    logger.info("Replaying %d spool file(s)", len(spool_files))

    # Collect all events with their mono_seq for sorting
    all_events: list[tuple[int, str]] = []

    for spool_file in spool_files:
        try:
            with open(spool_file) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        mono_seq = parsed.get("mono_seq", 0)
                        all_events.append((mono_seq, line))
                    except json.JSONDecodeError:
                        logger.warning(
                            "Malformed spool line in %s:%d",
                            spool_file.name, line_num,
                        )
        except OSError as e:
            logger.warning("Failed to read spool file %s: %s", spool_file, e)

    # Sort by mono_seq for causal ordering
    all_events.sort(key=lambda x: x[0])

    for _, event_json in all_events:
        yield event_json

    # Clean up spool files after successful yield
    for spool_file in spool_files:
        try:
            spool_file.unlink()
            logger.debug("Removed spool file: %s", spool_file.name)
        except OSError as e:
            logger.warning("Failed to remove spool file %s: %s", spool_file, e)


def ensure_spool_dir() -> None:
    """Create spool directory with secure permissions."""
    SPOOL_DIR.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
