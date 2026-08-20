"""The cairn dev-memory tools may only read THIS monorepo's projects.

WHY: the four cairn tools are registered into every room unconditionally and
close over no room scope, and cairn indexes every project on the host —
including somaNotes, a clinical product with PHI-adjacent material. The rooms
these tools live in contain two other humans. `project` was a model-supplied
hint, so any call that omitted it returned everything.

The fence is on the project and is enforced in the executors. A prompt rule
would be a request; this is a boundary.
"""

import asyncio

import pytest

from llm.tools import CAIRN_ALLOWED_PROJECTS, _build_cairn_tools, _cairn_allowed


PRIVATE = {"id": "s-private", "project": "somaNotes", "summary": "chart PHI"}
MINE = {"id": "s-mine", "project": "dialectic", "summary": "presence fence"}
TRADING = {"id": "s-td", "project": "trading", "summary": "oracle"}
UNLABELLED = {"id": "s-none", "summary": "no project key at all"}


def _tool(name):
    return next(t for t in _build_cairn_tools() if t.name == name)


class TestAllowlist:
    def test_somanotes_is_not_readable(self):
        assert "somaNotes" not in CAIRN_ALLOWED_PROJECTS

    def test_this_repo_is_readable(self):
        assert {"dialectic", "trading", "DwoodAmo"} <= set(CAIRN_ALLOWED_PROJECTS)

    def test_filter_keeps_only_allowed(self):
        assert _cairn_allowed([PRIVATE, MINE, TRADING]) == [MINE, TRADING]

    def test_unlabelled_rows_are_dropped_not_kept(self):
        """Fail closed: a row with no project is not proof it is ours."""
        assert _cairn_allowed([UNLABELLED]) == []

    def test_non_list_is_empty_not_passthrough(self):
        assert _cairn_allowed({"project": "dialectic"}) == []
        assert _cairn_allowed(None) == []


class TestExecutorsEnforceIt:
    def test_recent_dev_activity_filters_the_response(self, monkeypatch):
        from llm import cairn_client as cn

        async def fake_get(path, params=None, **kw):
            return [PRIVATE, MINE, TRADING]
        monkeypatch.setattr(cn, "get", fake_get)

        out = asyncio.run(_tool("recent_dev_activity").execute({}))
        projects = {s["project"] for s in out["sessions"]}
        assert "somaNotes" not in projects
        assert projects == {"dialectic", "trading"}
        assert out["count"] == 2

    def test_recent_dev_activity_refuses_a_foreign_project_outright(self):
        with pytest.raises(ValueError, match="not readable"):
            asyncio.run(
                _tool("recent_dev_activity").execute({"project": "somaNotes"})
            )

    def test_get_dev_session_cannot_be_walked_around_by_id(self, monkeypatch):
        """A session id fetched by hand must not bypass the fence."""
        from llm import cairn_client as cn

        async def fake_get(path, params=None, **kw):
            if path.endswith("/events"):
                return []
            return PRIVATE
        monkeypatch.setattr(cn, "get", fake_get)

        with pytest.raises(ValueError, match="not readable"):
            asyncio.run(_tool("get_dev_session").execute({"session_id": "s-private"}))

    def test_search_dev_sessions_filters_and_recounts(self, monkeypatch):
        from llm import cairn_client as cn

        async def fake_post(path, json=None, **kw):
            return {"count": 3, "results": [PRIVATE, MINE, TRADING]}
        monkeypatch.setattr(cn, "post", fake_post)

        out = asyncio.run(_tool("search_dev_sessions").execute({"query": "presence"}))
        assert out["count"] == 2, "count must reflect what was RETURNED, not what cairn had"
        assert all(s["project"] != "somaNotes" for s in out["sessions"])

    def test_search_dev_insights_filters_and_recounts(self, monkeypatch):
        from llm import cairn_client as cn

        async def fake_post(path, json=None, **kw):
            return {"count": 3, "results": [PRIVATE, MINE]}
        monkeypatch.setattr(cn, "post", fake_post)

        out = asyncio.run(_tool("search_dev_insights").execute({"query": "why"}))
        assert out["count"] == 1
        assert out["insights"] == [MINE]
