"""Tests for resource extraction from tool payloads."""
from __future__ import annotations

from cc_sidecar.reducer.extractor import extract_resource, normalize_tool_name


class TestNormalizeToolName:

    def test_task_to_agent(self):
        assert normalize_tool_name("Task") == "Agent"

    def test_agent_unchanged(self):
        assert normalize_tool_name("Agent") == "Agent"

    def test_read_unchanged(self):
        assert normalize_tool_name("Read") == "Read"


class TestExtractResource:

    def test_read_with_offset_and_limit(self):
        result = extract_resource("Read", {"file_path": "/home/user/src/models.py", "offset": 10, "limit": 40})
        assert result == "user/src/models.py:10-50"

    def test_read_without_range(self):
        result = extract_resource("Read", {"file_path": "/src/app.py"})
        assert result == "/src/app.py"

    def test_read_with_offset_only(self):
        result = extract_resource("Read", {"file_path": "/a/b/c/d.py", "offset": 100})
        assert result == "b/c/d.py:100-"

    def test_write(self):
        result = extract_resource("Write", {"file_path": "/home/user/project/new_file.py"})
        assert result == "user/project/new_file.py"

    def test_edit(self):
        result = extract_resource("Edit", {"file_path": "/home/user/project/existing.py"})
        assert result == "user/project/existing.py"

    def test_bash_short(self):
        result = extract_resource("Bash", {"command": "npm test"})
        assert result == "npm test"

    def test_bash_truncated(self):
        long_cmd = "python -m pytest tests/ -v --tb=long --cov=mypackage --cov-report=html --timeout=300"
        result = extract_resource("Bash", {"command": long_cmd})
        assert len(result) <= 60
        assert result.endswith("…")

    def test_glob_with_path(self):
        result = extract_resource("Glob", {"pattern": "**/*.py", "path": "/home/user/src"})
        assert result == "**/*.py in home/user/src"

    def test_glob_without_path(self):
        result = extract_resource("Glob", {"pattern": "*.ts"})
        assert result == "*.ts"

    def test_grep_with_glob(self):
        result = extract_resource("Grep", {"pattern": "TODO", "glob": "*.ts"})
        assert result == "/TODO/ in *.ts"

    def test_grep_without_glob(self):
        result = extract_resource("Grep", {"pattern": "function\\s+\\w+"})
        assert "function" in result

    def test_agent(self):
        result = extract_resource("Agent", {
            "subagent_type": "Explore",
            "prompt": "Find all test files in the project",
        })
        assert result.startswith("Explore:")
        assert "Find all test" in result

    def test_task_alias(self):
        """Task should be normalized to Agent before extraction."""
        result = extract_resource("Task", {
            "subagent_type": "test-runner",
            "prompt": "Run all tests",
        })
        assert result.startswith("test-runner:")

    def test_agent_background(self):
        result = extract_resource("Agent", {
            "subagent_type": "build",
            "prompt": "Build the project",
            "run_in_background": True,
        })
        assert "[bg]" in result

    def test_webfetch(self):
        result = extract_resource("WebFetch", {"url": "https://api.example.com/v1/data"})
        assert result == "fetch: api.example.com"

    def test_websearch(self):
        result = extract_resource("WebSearch", {"query": "SQLite WAL mode performance"})
        assert result == "search: 'SQLite WAL mode performance'"

    def test_mcp_tool(self):
        result = extract_resource("mcp__github__search_code", {"query": "function main"})
        assert result == "mcp:github/search_code(function main)"

    def test_mcp_tool_no_args(self):
        result = extract_resource("mcp__zoekt__status", {})
        assert result == "mcp:zoekt/status"

    def test_unknown_tool(self):
        result = extract_resource("CustomTool", {"arg": "value"})
        assert result == "CustomTool"

    def test_empty_input(self):
        result = extract_resource("Read", {})
        assert result == "?"
