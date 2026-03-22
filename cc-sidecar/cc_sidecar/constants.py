"""
cc-sidecar path conventions, timeouts, and version constants.

ARCHITECTURE: All runtime paths follow XDG Base Directory conventions.
WHY: Ensures multi-user isolation, predictable discovery, and
correct file permissions on shared machines.
"""
from __future__ import annotations

import os
from pathlib import Path

# ============================================================
# Version
# ============================================================
VERSION = "0.1.0"
EMITTER_VERSION = f"cc-sidecar/{VERSION}"

# ============================================================
# XDG paths
# ============================================================

def _xdg_runtime_dir() -> Path:
    """$XDG_RUNTIME_DIR with fallback to /tmp/cc-sidecar-<uid>."""
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg)
    return Path(f"/tmp/cc-sidecar-{os.getuid()}")


def _xdg_data_home() -> Path:
    """$XDG_DATA_HOME with fallback to ~/.local/share."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


# WHY: Ephemeral runtime artifacts (socket, spool, PID, auth token)
# go in XDG_RUNTIME_DIR — typically /run/user/<uid>/, mode 0700,
# automatically cleaned on reboot.
RUNTIME_DIR = _xdg_runtime_dir() / "cc-sidecar"

# WHY: Persistent data (SQLite database) goes in XDG_DATA_HOME
# so it survives reboots but stays user-scoped.
DATA_DIR = _xdg_data_home() / "cc-sidecar"

# ============================================================
# Socket and file paths
# ============================================================
DAEMON_SOCKET_PATH = RUNTIME_DIR / "daemon.sock"
SPOOL_DIR = RUNTIME_DIR / "spool"
PID_FILE = RUNTIME_DIR / "daemon.pid"
AUTH_TOKEN_FILE = RUNTIME_DIR / "auth.token"
STATUSLINE_FILE = RUNTIME_DIR / "statusline.json"
SEQ_FILE = RUNTIME_DIR / "seq"

DATABASE_PATH = DATA_DIR / "events.db"

# ============================================================
# File permissions
# ============================================================
DIR_MODE = 0o700
FILE_MODE = 0o600

# ============================================================
# Timeouts (milliseconds unless noted)
# ============================================================
EMIT_SOCKET_TIMEOUT_S = 0.2        # 200ms — max time emit waits for socket write
EMIT_INTERNAL_TIMEOUT_S = 2.0      # 2s — max total time for emit CLI
SPOOL_MAX_BYTES = 50 * 1024 * 1024  # 50MB per spool file

# ============================================================
# Stuck/orphan detection thresholds (seconds)
# ============================================================
STUCK_WARN_THRESHOLD_S = 60
STUCK_ALERT_THRESHOLD_S = 120
ORPHAN_THRESHOLD_S = 300
BASH_EXTENDED_THRESHOLD_S = 180    # long-running Bash commands
ORPHAN_SCAN_INTERVAL_S = 10

# ============================================================
# WebSocket
# ============================================================
WS_DEFAULT_PORT = 7420
WS_DEBOUNCE_MS = 200

# ============================================================
# Retention
# ============================================================
RAW_EVENT_RETENTION_DAYS = 7
SESSION_RETENTION_DAYS = 30
VACUUM_INTERVAL_S = 3600  # 1 hour

# ============================================================
# Payload limits
# ============================================================
PAYLOAD_TRUNCATE_BYTES = 100 * 1024  # 100KB — truncate larger payloads

# ============================================================
# Tool aliases
# ============================================================
# WHY: Task tool was renamed to Agent in Claude Code ~v2.1.50-63.
# Task(...) is retained as an alias. Normalize to canonical name.
TOOL_ALIASES: dict[str, str] = {
    "Task": "Agent",
}
