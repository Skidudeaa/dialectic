"""A Reddit evidence excerpt shows words people wrote -- the post body, then
comments as `u/name: body` -- not the markdown header that
reddit_client.extract_article puts in front of them. The content strings below
follow that function's exact section layout."""
from llm.tools import EVIDENCE_EXCERPT_CHARS, evidence_of

URL = "https://www.reddit.com/r/t/comments/abc/x/"
HEADER = (
    "# Holy title\n\n"
    "r/t · u/op · 2026-09-08T00:00:00+00:00\n"
    f"[Original discussion]({URL}) · 41 points\n\n"
)
NOTE = (
    "## Comments\n\nShowing 2 API-loaded comments sorted by top; Reddit reports 9 total. "
    "This is a bounded sample; omitted branches are not evidence of absence."
)


def _comment(author: str, body: str) -> str:
    return (
        f"### u/{author} · 7 points · 2026-09-08T01:00:00+00:00\n"
        f"[Comment t1_c1]({URL}c1/) · parent t3_abc\n\n{body}"
    )


def _raw(selftext: str, *comments: str) -> dict:
    content = "\n\n".join([HEADER.rstrip("\n"), selftext, NOTE, *comments])
    return {"url": URL, "title": "Holy title", "author": "op",
            "content": content, "source": "reddit_api"}


def test_self_post_excerpt_starts_at_the_post_body():
    (item,) = evidence_of("read_reddit", _raw("The body a person wrote.", _comment("a", "First reply.")))
    assert item["excerpt"].startswith("The body a person wrote.")
    assert "[Original discussion]" not in item["excerpt"]
    assert "# Holy title" not in item["excerpt"]
    # attribution is carried by the item's own fields, never lost with the header
    assert item["title"] == "Holy title" and item["author"] == "op" and item["kind"] == "reddit"


def test_link_post_excerpt_is_its_comments_each_under_their_own_name():
    placeholder = ("Linked source: https://example.com/a\n\n"
                   "The linked article body is not included; read its URL separately.")
    (item,) = evidence_of("read_reddit", _raw(placeholder, _comment("a", "First reply."), _comment("b", "Second.")))
    # The card's byline is the OP; a commenter's words must carry their own name.
    assert item["excerpt"].startswith("u/a: First reply.")
    assert "u/b: Second." in item["excerpt"]
    assert "Showing 2 API-loaded" not in item["excerpt"]
    assert "[Comment " not in item["excerpt"] and "###" not in item["excerpt"]


def test_link_post_without_comments_keeps_the_linked_source_line():
    placeholder = ("Linked source: https://example.com/a\n\n"
                   "The linked article body is not included; read its URL separately.")
    (item,) = evidence_of("read_reddit", _raw(placeholder))
    assert item["excerpt"].startswith("Linked source: https://example.com/a")


def test_read_article_routed_to_reddit_gets_the_same_treatment():
    (item,) = evidence_of("read_article", _raw("Body via read_article.", _comment("a", "r")))
    assert item["kind"] == "reddit" and item["excerpt"].startswith("Body via read_article.")


def test_truncation_is_measured_after_the_header_is_dropped():
    body = "w" * (EVIDENCE_EXCERPT_CHARS - 5)
    (item,) = evidence_of("read_reddit", {"url": URL, "source": "reddit_api",
                                          "content": HEADER + body})
    assert item["excerpt"] == body and item["excerpt_truncated"] is False


def test_unrecognised_reddit_content_and_plain_articles_are_untouched():
    (odd,) = evidence_of("read_reddit", {"url": URL, "content": "post", "source": "reddit_api"})
    assert odd["excerpt"] == "post"
    (article,) = evidence_of("read_article", {"url": "https://example.com/a",
                                               "content": "# A heading\n\nArticle text."})
    assert article["kind"] == "article" and article["excerpt"].startswith("# A heading")


def test_continuation_window_is_untouched():
    (item,) = evidence_of("read_reddit", {"url": URL, "source": "reddit_api",
                                          "content": "mid-thread text", "content_start": 9000})
    assert item["excerpt"] == "mid-thread text" and item["content_start"] == 9000

