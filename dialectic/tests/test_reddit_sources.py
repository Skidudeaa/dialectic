"""Read-only Reddit, explicit source windows, and existing filing contracts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from llm import defuddle_client as dc
from llm import reddit_client as rc
from llm.tools import ARTICLE_CONTENT_CAP, TOOL_RESULT_CHAR_CAP, _article_window, build_registry, serialize_tool_result


class Client:
    def __init__(self) -> None:
        self.closed = False
        self.subreddit = AsyncMock()
        self.submission = AsyncMock()
        self.comment = AsyncMock()

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


def post() -> SimpleNamespace:
    comment = SimpleNamespace(
        id="comment1", name="t1_comment1", link_id="t3_post1", parent_id="t3_post1",
        author="Dan", score=7, created_utc=1788800000,
        permalink="/r/test/comments/post1/title/comment1/", body="A specific, attributable reply.",
        load=AsyncMock(),
    )
    return SimpleNamespace(
        id="post1", name="t3_post1", title="A source question", author="Amo", subreddit="test",
        permalink="/r/test/comments/post1/title/", url="https://publisher.example/source",
        selftext="The original post, preserved in full.", created_utc=1788800000,
        score=22, num_comments=48, load=AsyncMock(),
        comments=SimpleNamespace(replace_more=AsyncMock(), list=lambda: [comment]),
    )


@pytest.mark.asyncio
async def test_search_is_real_listing_with_attributed_excerpts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    item = post()
    item.selftext = "x" * 700

    async def listing(*args: object, **kwargs: object):
        assert args == ("specific claim",)
        assert kwargs == {"sort": "top", "time_filter": "week", "limit": 2}
        yield item

    client.subreddit.return_value = SimpleNamespace(search=listing)
    monkeypatch.setattr(rc, "_client", lambda: client)
    result = await rc.search("specific claim", subreddit="r/test", sort="top", time_filter="week", limit=2)
    client.subreddit.assert_awaited_once_with("test")
    assert client.closed
    assert result["results"][0]["url"] == "https://www.reddit.com/r/test/comments/post1/title/"
    assert result["results"][0]["excerpt_truncated"] is True
    assert result["results"][0]["author"] == "Amo"
    assert result["source"] == "reddit_api"


@pytest.mark.asyncio
async def test_browse_top_uses_time_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()

    async def listing(**kwargs: object):
        assert kwargs == {"time_filter": "month", "limit": 1}
        yield post()

    client.subreddit.return_value = SimpleNamespace(top=listing)
    monkeypatch.setattr(rc, "_client", lambda: client)
    assert (await rc.search(sort="top", time_filter="month", limit=1))["count"] == 1


@pytest.mark.asyncio
async def test_post_keeps_body_comment_parent_and_sampling_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    item = post()
    client.submission.return_value = item
    monkeypatch.setattr(rc, "_client", lambda: client)
    article = await rc.extract_article("https://redd.it/post1", comment_limit=5, sort="new")
    client.submission.assert_awaited_once_with(id="post1", fetch=False)
    assert item.comment_sort == "new"
    assert item.comment_limit == 5
    item.comments.replace_more.assert_awaited_once_with(limit=0)
    assert item.selftext in article["content"]
    assert "parent t3_post1" in article["content"]
    assert "A specific, attributable reply." in article["content"]
    assert "48 total" in article["content_note"]
    assert article["comments_returned"] == 1
    assert client.closed


@pytest.mark.asyncio
async def test_exact_comment_is_fetched_even_outside_the_loaded_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    item = post()
    selected = item.comments.list()[0]
    client.submission.return_value = item
    client.comment.return_value = selected
    monkeypatch.setattr(rc, "_client", lambda: client)
    article = await rc.extract_article("https://www.reddit.com/r/test/comments/post1/title/comment1/")
    client.comment.assert_awaited_once_with(id="comment1", fetch=False)
    selected.load.assert_awaited_once()
    item.comments.replace_more.assert_not_awaited()
    assert "Exact linked comment comment1" in article["content_note"]


@pytest.mark.asyncio
async def test_wrong_post_comment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    item = post()
    selected = item.comments.list()[0]
    selected.link_id = "t3_somewhereelse"
    client.submission.return_value = item
    client.comment.return_value = selected
    monkeypatch.setattr(rc, "_client", lambda: client)
    with pytest.raises(rc.RedditError, match="does not belong"):
        await rc.extract_article("https://reddit.com/comments/post1/title/comment1")
    assert client.closed


def test_missing_credentials_names_keys_without_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "must-never-appear")
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)
    with pytest.raises(rc.RedditError) as error:
        rc._client()
    assert "REDDIT_CLIENT_ID" in str(error.value)
    assert "must-never-appear" not in str(error.value)


@pytest.mark.parametrize("url", [
    "https://reddit.com.evil.example/comments/post1", "https://user:password@reddit.com/comments/post1",
    "http://127.0.0.1/comments/post1", "https://reddit.com/r/test/", "https://reddit.com/r/test/s/sharetoken",
])
def test_invalid_or_nonpost_targets_fail_before_any_fetch(url: str) -> None:
    with pytest.raises(ValueError):
        rc._target(url)


@pytest.mark.asyncio
async def test_article_and_human_accept_share_authenticated_reddit_route(monkeypatch: pytest.MonkeyPatch) -> None:
    extract = AsyncMock(return_value={"content": "A real fetched post.", "title": "Post", "source": "reddit_api"})
    monkeypatch.setattr(rc, "extract_article", extract)
    result = await dc.extract_article("https://reddit.com/comments/post1")
    assert result["source"] == "reddit_api"
    extract.assert_awaited_once_with("https://reddit.com/comments/post1")
    extract.side_effect = rc.RedditError("Reddit refused access")
    with pytest.raises(dc.DefuddleError, match="refused access"):
        await dc.extract_article("https://reddit.com/comments/post1")


@pytest.mark.asyncio
async def test_reddit_library_tool_still_only_proposes(room, monkeypatch: pytest.MonkeyPatch) -> None:
    extract = AsyncMock(return_value={"content": "A real post.", "title": "Post", "site": "Reddit"})
    monkeypatch.setattr(rc, "extract_article", extract)
    db = SimpleNamespace(execute=AsyncMock(), fetch=AsyncMock())
    result = await build_registry(room, db).get("save_reading").execute({
        "url": "https://reddit.com/comments/post1", "summary": "The room should inspect this claim.",
    })
    assert result["provenance"] == {"kind": "reading_draft"}
    assert "content" not in result["proposal"]
    db.execute.assert_not_awaited()
    db.fetch.assert_not_awaited()


def test_long_article_can_be_read_to_the_end_without_missing_text() -> None:
    article = {"content": "first " * 1700 + "last section", "word_count": 1702}
    result = _article_window(article, {}, "https://example.com/article")
    assert len(result["content"]) == ARTICLE_CONTENT_CAP
    continued = _article_window(article, {
        "start_char": result["next_start_char"], "content_sha256": result["content_sha256"],
    }, "https://example.com/article")
    assert result["content"] + continued["content"] == article["content"]
    assert "next_start_char" not in continued
    with pytest.raises(ValueError, match="changed"):
        _article_window({"content": "different"}, {"content_sha256": result["content_sha256"]}, "https://example.com")


def test_targeted_later_passage_and_unicode_preserve_valid_complete_json() -> None:
    article = {"content": "前" * 9000 + "load-bearing claim" + "後" * 9000}
    result = _article_window(article, {"find": "load-bearing claim"}, "https://example.com")
    assert "load-bearing claim" in result["content"]
    assert result["content_start"] == 8650
    assert len(serialize_tool_result(result)) <= TOOL_RESULT_CHAR_CAP
    assert json.loads(serialize_tool_result(result)) == result
    with pytest.raises(ValueError, match="not found"):
        _article_window(article, {"find": "invented claim"}, "https://example.com")
