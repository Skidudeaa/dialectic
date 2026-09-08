"""Read public Reddit discussions with the configured application credentials."""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import asyncpraw
from asyncprawcore.exceptions import AsyncPrawcoreException

TIMEOUT_S = 20.0
REDDIT_HOSTS = frozenset({"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com", "m.reddit.com", "redd.it"})
SORTS = ("relevance", "top", "new", "hot", "comments")
TIME_FILTERS = ("all", "hour", "day", "week", "month", "year")


class RedditError(Exception):
    """Reddit configuration, access, or fetch failure that the room can report."""


def is_reddit_url(url: str) -> bool:
    """Identify Reddit hosts without treating suffix lookalikes as Reddit."""
    return urlsplit(url).hostname in REDDIT_HOSTS


def _client() -> asyncpraw.Reddit:
    keys = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        raise RedditError("Reddit is not configured: missing " + ", ".join(missing))
    # App-only OAuth can read public discussions and cannot act as the owner.
    client = asyncpraw.Reddit(
        client_id=os.environ[keys[0]], client_secret=os.environ[keys[1]],
        user_agent=os.environ[keys[2]], check_for_async=False,
        requestor_kwargs={"timeout": 12},
    )
    client.read_only = True
    return client


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _post_summary(post: Any) -> dict[str, Any]:
    body = post.selftext or ""
    return {
        "id": post.id, "title": post.title,
        "url": "https://www.reddit.com" + post.permalink,
        "linked_url": post.url, "subreddit": str(post.subreddit),
        "author": str(post.author) if post.author else "[deleted]",
        "published": _timestamp(post.created_utc), "score": post.score,
        "comment_count": post.num_comments, "excerpt": body[:350],
        "excerpt_truncated": len(body) > 350,
    }


async def search(
    query: str = "", *, subreddit: str = "all", sort: str = "relevance",
    time_filter: str = "all", limit: int = 5,
) -> dict[str, Any]:
    """Search public submissions or browse a community; never write to Reddit."""
    subreddit = subreddit.removeprefix("r/").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", subreddit):
        raise ValueError("subreddit must be a community name, or names joined by +")
    if sort not in SORTS or time_filter not in TIME_FILTERS:
        raise ValueError("unsupported Reddit sort or time_filter")
    if not 1 <= limit <= 6:
        raise ValueError("limit must be between 1 and 6")
    if len(query) > 500:
        raise ValueError("query must be 500 characters or fewer")
    if not query and sort not in {"top", "new", "hot"}:
        raise ValueError("provide a query, or browse with sort top, new, or hot")
    try:
        async with asyncio.timeout(TIMEOUT_S), _client() as reddit:
            community = await reddit.subreddit(subreddit)
            if query:
                listing = community.search(query, sort=sort, time_filter=time_filter, limit=limit)
            elif sort == "top":
                listing = community.top(time_filter=time_filter, limit=limit)
            else:
                listing = getattr(community, sort)(limit=limit)
            posts = [_post_summary(post) async for post in listing]
    except TimeoutError as exc:
        raise RedditError(f"Reddit search timed out after {TIMEOUT_S:g}s") from exc
    except AsyncPrawcoreException as exc:
        raise RedditError(f"Reddit search failed: {type(exc).__name__}: {exc}") from exc
    return {
        "source": "reddit_api", "query": query, "subreddit": subreddit,
        "sort": sort, "time_filter": time_filter, "count": len(posts),
        "results": posts, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "note": "Search excerpts only. Read a result before quoting it; scores measure voting, not truth."
        if posts else "No Reddit submissions matched this query and filter.",
    }


def _target(url: str) -> tuple[str, str | None]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in REDDIT_HOSTS or parsed.username or parsed.password:
        raise ValueError("use a public Reddit post or comment permalink")
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "redd.it" and len(parts) == 1:
        post_id, comment_id = parts[0], None
    elif "comments" in parts:
        tail = parts[parts.index("comments") + 1:]
        post_id = tail[0] if tail else ""
        comment_id = tail[2] if len(tail) > 2 else None
    else:
        raise ValueError("use a Reddit post permalink; use search_reddit to browse a community or find a topic")
    if not re.fullmatch(r"[a-z0-9]+", post_id) or (comment_id and not re.fullmatch(r"[a-z0-9]+", comment_id)):
        raise ValueError("the Reddit permalink contains an invalid post or comment ID")
    return post_id, comment_id


def _comment_markdown(comment: Any) -> str:
    author = str(comment.author) if comment.author else "[deleted]"
    return (
        f"### u/{author} · {comment.score} points · {_timestamp(comment.created_utc)}\n"
        f"[Comment {comment.name}](https://www.reddit.com{comment.permalink}) · parent {comment.parent_id}\n\n"
        f"{comment.body}"
    )


async def extract_article(url: str, *, comment_limit: int = 12, sort: str = "top") -> dict[str, Any]:
    """Read a post and a bounded comment sample, or one exact comment permalink."""
    post_id, comment_id = _target(url)
    if not 0 <= comment_limit <= 30:
        raise ValueError("comment_limit must be between 0 and 30")
    if sort not in {"top", "new", "confidence", "controversial", "old", "q&a"}:
        raise ValueError("unsupported Reddit comment sort")
    try:
        async with asyncio.timeout(TIMEOUT_S), _client() as reddit:
            post = await reddit.submission(id=post_id, fetch=False)
            post.comment_sort = sort
            post.comment_limit = max(1, comment_limit)
            await post.load()
            summary = _post_summary(post)
            if comment_id:
                comment = await reddit.comment(id=comment_id, fetch=False)
                await comment.load()
                if comment.link_id != post.name:
                    raise RedditError("The comment does not belong to the linked post")
                comments = [comment]
            else:
                # No unbounded MoreComments expansion or hidden extra API calls.
                await post.comments.replace_more(limit=0)
                comments = list(post.comments.list())[:comment_limit]
            note = (
                f"Exact linked comment {comment_id}; other comments are not included."
                if comment_id else
                f"Showing {len(comments)} API-loaded comments sorted by {sort}; Reddit reports {post.num_comments} total. "
                "This is a bounded sample; omitted branches are not evidence of absence."
            )
            sections = [
                f"# {post.title}",
                f"r/{post.subreddit} · u/{summary['author']} · {summary['published']}\n"
                f"[Original discussion]({summary['url']}) · {post.score} points",
                post.selftext or f"Linked source: {post.url}\n\nThe linked article body is not included; read its URL separately.",
                f"## Comments\n\n{note}",
                *[_comment_markdown(comment) for comment in comments],
            ]
            content = "\n\n".join(sections)
            return {
                "url": url, "title": post.title, "author": summary["author"],
                "site": f"Reddit · r/{post.subreddit}", "published": summary["published"],
                "content": content, "word_count": len(content.split()),
                "source": "reddit_api", "linked_url": post.url,
                "comment_count": post.num_comments, "comments_returned": len(comments),
                "content_note": note, "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
    except TimeoutError as exc:
        raise RedditError(f"Reddit fetch timed out after {TIMEOUT_S:g}s") from exc
    except AsyncPrawcoreException as exc:
        raise RedditError(f"Reddit fetch failed: {type(exc).__name__}: {exc}") from exc
