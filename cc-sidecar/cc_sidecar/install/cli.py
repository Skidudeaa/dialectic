"""
Install cc-sidecar hooks into Claude Code settings.

ARCHITECTURE: Generates the hooks JSON and optionally writes it to
the user's settings.json at ~/.claude/settings.json.
WHY: Automating installation prevents configuration errors and
ensures all required hook events are captured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


# WHY: All hook events that cc-sidecar needs to observe.
# Each uses the Go emit binary for <5ms latency.
HOOK_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCompleted",
    "ConfigChange",
    "InstructionsLoaded",
    "PreCompact",
    "PostCompact",
    "Stop",
    "StopFailure",
    "SessionEnd",
]


def generate_hooks_config(emit_command: str = "cc-sidecar-emit") -> dict:
    """
    Generate the hooks configuration for Claude Code settings.json.

    Args:
        emit_command: Path or name of the emit binary.
    """
    hooks: dict = {}

    for event in HOOK_EVENTS:
        hooks[event] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": emit_command,
                        "timeout": 5,
                    }
                ]
            }
        ]

    return {"hooks": hooks}


def generate_subagent_frontmatter(emit_command: str = "cc-sidecar-emit") -> str:
    """
    Generate YAML frontmatter for custom subagents with full telemetry.

    This gives Mode B (full) visibility into subagent tool calls.
    """
    cmd = f"{emit_command} --subagent"
    return f"""hooks:
  PreToolUse:
    - matcher: ".*"
      hooks:
        - type: command
          command: "{cmd}"
  PostToolUse:
    - matcher: ".*"
      hooks:
        - type: command
          command: "{cmd}"
  PostToolUseFailure:
    - matcher: ".*"
      hooks:
        - type: command
          command: "{cmd}"
  PermissionRequest:
    - hooks:
        - type: command
          command: "{cmd}"
  Stop:
    - hooks:
        - type: command
          command: "{cmd}"
"""


def install_hooks(
    scope: str = "user",
    emit_command: str = "cc-sidecar-emit",
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Install hooks into Claude Code settings.

    Args:
        scope: "user", "project", or "local"
        emit_command: Path to the emit binary
        dry_run: If True, print the config without writing

    Returns:
        Path to the modified settings file, or None on dry run.
    """
    # Determine settings file path
    if scope == "user":
        settings_path = Path.home() / ".claude" / "settings.json"
    elif scope == "project":
        settings_path = Path(".claude") / "settings.json"
    elif scope == "local":
        settings_path = Path(".claude") / "settings.local.json"
    else:
        print(f"Unknown scope: {scope}", file=sys.stderr)
        return None

    config = generate_hooks_config(emit_command)

    if dry_run:
        print(json.dumps(config, indent=2))
        return None

    # Read existing settings
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: {settings_path} contains invalid JSON, creating new", file=sys.stderr)

    # Merge hooks (preserve existing non-sidecar hooks)
    if "hooks" not in existing:
        existing["hooks"] = {}

    for event, hook_config in config["hooks"].items():
        if event in existing["hooks"]:
            # Check if sidecar hook already exists
            has_sidecar = any(
                emit_command in str(h)
                for entry in existing["hooks"][event]
                for h in entry.get("hooks", [])
            )
            if not has_sidecar:
                existing["hooks"][event].extend(hook_config)
        else:
            existing["hooks"][event] = hook_config

    # Write back
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"Hooks installed to {settings_path}")
    return settings_path


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Install cc-sidecar hooks into Claude Code")
    parser.add_argument(
        "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Settings scope (default: user)",
    )
    parser.add_argument(
        "--emit-command",
        default="cc-sidecar-emit",
        help="Path to the emit binary (default: cc-sidecar-emit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print config without writing",
    )
    parser.add_argument(
        "--subagent-frontmatter",
        action="store_true",
        help="Print subagent frontmatter YAML instead of installing hooks",
    )

    args = parser.parse_args()

    if args.subagent_frontmatter:
        print(generate_subagent_frontmatter(args.emit_command))
    else:
        install_hooks(
            scope=args.scope,
            emit_command=args.emit_command,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
