"""
Secret redaction pipeline for cc-sidecar.

ARCHITECTURE: Pattern-based scrubbing applied before ANY persistence —
both daemon SQLite writes and emit spool file writes.
WHY: The sidecar observes prompts, file contents, bash commands, and
tool arguments that routinely contain API keys, tokens, and credentials.
Without redaction, the SQLite DB is an unprotected credential aggregator.
TRADEOFF: Regex-based redaction may produce false positives (redacting
non-secret strings that match patterns) or false negatives (novel secret
formats). We prefer false positives — safer to over-redact.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

# ============================================================
# Redaction marker
# ============================================================
REDACTED = "[REDACTED]"

# ============================================================
# Known secret prefixes and patterns
# ============================================================

# WHY: These patterns cover Anthropic, OpenAI, GitHub, AWS, GCP, Stripe,
# Voyage, and generic Bearer/Authorization tokens. Each pattern matches
# the prefix followed by non-whitespace characters.
_SECRET_PREFIX_PATTERNS = [
    # Anthropic
    r"sk-ant-[a-zA-Z0-9_-]+",
    # OpenAI
    r"sk-[a-zA-Z0-9]{20,}",
    # GitHub tokens
    r"ghp_[a-zA-Z0-9]{36,}",
    r"gho_[a-zA-Z0-9]{36,}",
    r"ghs_[a-zA-Z0-9]{36,}",
    r"ghu_[a-zA-Z0-9]{36,}",
    r"github_pat_[a-zA-Z0-9_]{22,}",
    # AWS
    r"AKIA[A-Z0-9]{16}",
    r"aws_secret_access_key\s*=\s*\S+",
    # Stripe
    r"sk_live_[a-zA-Z0-9]{24,}",
    r"sk_test_[a-zA-Z0-9]{24,}",
    r"pk_live_[a-zA-Z0-9]{24,}",
    r"pk_test_[a-zA-Z0-9]{24,}",
    # Voyage AI
    r"pa-[a-zA-Z0-9_-]{20,}",
    # Generic bearer/auth
    r"Bearer\s+[a-zA-Z0-9_.~+/=-]{20,}",
    r"Authorization:\s*(?:Bearer\s+)?[a-zA-Z0-9_.~+/=-]{20,}",
]

# WHY: Environment variable assignments with sensitive-sounding names.
_ENV_VAR_PATTERNS = [
    r"export\s+\w*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIALS|API_KEY)\w*\s*=\s*['\"]?[^\s'\"]+['\"]?",
    r"\w*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIALS|API_KEY)\w*\s*=\s*['\"]?[^\s'\"]+['\"]?",
]

# WHY: Database connection strings often contain passwords.
_CONNECTION_STRING_PATTERNS = [
    r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^@\s]+@[^\s]+",
]

# Compile all patterns into a single regex for performance
_ALL_PATTERNS = _SECRET_PREFIX_PATTERNS + _ENV_VAR_PATTERNS + _CONNECTION_STRING_PATTERNS
_REDACTION_RE = re.compile("|".join(f"({p})" for p in _ALL_PATTERNS), re.IGNORECASE)


# ============================================================
# High-entropy string detection
# ============================================================

def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in freq.values()
    )


def _is_high_entropy_secret(s: str) -> bool:
    """
    Detect potential secrets by high entropy + length.

    WHY: Catches API keys and tokens that don't match known prefixes.
    TRADEOFF: May flag base64-encoded content or UUIDs. We accept this
    because the redacted version still shows the key name/context.
    """
    if len(s) < 24:
        return False
    # Skip common non-secret high-entropy strings
    if s.startswith(("http://", "https://", "/", "./", "../")):
        return False
    entropy = _shannon_entropy(s)
    # Threshold: random alphanumeric strings typically have entropy > 4.5
    return entropy > 4.5


# ============================================================
# Core redaction functions
# ============================================================

def redact_string(text: str) -> str:
    """
    Apply all redaction patterns to a string.
    Returns the string with secrets replaced by [REDACTED].
    """
    return _REDACTION_RE.sub(REDACTED, text)


def redact_value(value: Any, key: str = "") -> Any:
    """
    Recursively redact secrets from a JSON-compatible value.

    Args:
        value: The value to redact (str, dict, list, or primitive).
        key: The parent key name, used for context-aware redaction.
    """
    if isinstance(value, str):
        # Always apply pattern-based redaction
        result = redact_string(value)
        # For values under sensitive-sounding keys, also check entropy
        sensitive_key = any(
            kw in key.lower()
            for kw in ("key", "secret", "token", "password", "credential", "auth")
        )
        if sensitive_key and _is_high_entropy_secret(value):
            return REDACTED
        return result
    elif isinstance(value, dict):
        return {k: redact_value(v, key=k) for k, v in value.items()}
    elif isinstance(value, list):
        return [redact_value(item, key=key) for item in value]
    else:
        return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Redact secrets from a hook event payload.

    This is the primary entry point. Called by both the emit CLI
    (before spooling) and the daemon (before SQLite insertion).
    """
    return redact_value(payload)


def redact_json_string(json_str: str) -> str:
    """
    Parse a JSON string, redact it, and re-serialize.

    Falls back to string-level redaction if JSON parsing fails.
    """
    try:
        data = json.loads(json_str)
        redacted = redact_payload(data)
        return json.dumps(redacted, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return redact_string(json_str)
