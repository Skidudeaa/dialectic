"""Tests for the secret redaction pipeline."""
from __future__ import annotations

from cc_sidecar.daemon.redact import redact_payload, redact_string, REDACTED


class TestRedactString:

    def test_anthropic_key(self):
        result = redact_string("key: sk-ant-abc123def456-long-key-value")
        assert REDACTED in result
        assert "sk-ant-" not in result

    def test_openai_key(self):
        result = redact_string("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz")
        assert REDACTED in result

    def test_github_token(self):
        result = redact_string("token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl")
        assert REDACTED in result

    def test_voyage_key(self):
        result = redact_string("export VOYAGEAI_API_KEY='pa-ALdFBD5rOO0m5xGn7aVnnV6hLLHCkhJztypLnei2fWW'")
        assert REDACTED in result
        assert "pa-ALdFBD5r" not in result

    def test_bearer_token(self):
        result = redact_string("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature")
        assert REDACTED in result

    def test_postgres_connection_string(self):
        result = redact_string("DATABASE_URL=postgresql://user:password123@localhost/mydb")
        assert REDACTED in result
        assert "password123" not in result

    def test_env_var_export(self):
        result = redact_string("export API_KEY=some-secret-value-here")
        assert REDACTED in result

    def test_safe_text_unchanged(self):
        text = "This is a normal log message with no secrets"
        assert redact_string(text) == text

    def test_aws_key(self):
        result = redact_string("aws_access_key_id = AKIAIOSFODNN7EXAMPLE")
        assert REDACTED in result


class TestRedactPayload:

    def test_nested_dict(self):
        payload = {
            "command": "export API_KEY=sk-ant-secret123456789012345",
            "nested": {
                "token": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            },
        }
        result = redact_payload(payload)
        assert REDACTED in result["command"]
        assert REDACTED in result["nested"]["token"]

    def test_list_values(self):
        payload = {
            "args": ["--key", "sk-ant-abcdef1234567890abcdef"],
        }
        result = redact_payload(payload)
        assert REDACTED in result["args"][1]

    def test_non_secret_preserved(self):
        payload = {
            "file_path": "/home/user/src/main.py",
            "line_count": 42,
            "is_binary": False,
        }
        result = redact_payload(payload)
        assert result == payload

    def test_mixed_payload(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "curl -H 'Authorization: Bearer sk-ant-secret123' https://api.example.com",
            },
            "session_id": "abc123",
        }
        result = redact_payload(payload)
        assert result["tool_name"] == "Bash"
        assert result["session_id"] == "abc123"
        assert "sk-ant-" not in result["tool_input"]["command"]
