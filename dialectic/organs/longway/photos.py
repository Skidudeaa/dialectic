"""Freely licensed Commons photographs, with credit taken from the file metadata."""
import asyncio
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime
import fcntl
from html import unescape
import os
from pathlib import Path
import re
import stat
import tempfile
import time

import httpx


_FREE = re.compile(r"CC0(?: 1\.0)?|public domain|CC BY(?:-SA)?(?: \d+(?:\.\d+)?)?", re.I)


def candidates(payload):
    found = []
    for page in payload.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            meta = info.get("extmetadata", {})

            def field(key):
                return " ".join(unescape(re.sub(r"<[^>]+>", " ", meta.get(key, {}).get("value", ""))).split())

            licence, author = field("LicenseShortName"), field("Artist")
            width = info.get("width", 0)
            if (not author or not _FREE.fullmatch(licence) or width < 1200
                    or info.get("thumbwidth", width) < 1200 or not info.get("thumburl")
                    or not info.get("descriptionurl") or not info.get("mime", "").startswith("image/")):
                continue
            found.append(dict(title=page["title"], page=info["descriptionurl"], url=info["thumburl"],
                              author=author, licence=licence, licence_url=field("LicenseUrl") or None,
                              width=width, height=info["height"]))
            if len(found) == 8:
                return found
    return found


def _postpone(file, seconds):
    file.seek(0)
    file.write(str(time.time() + seconds))
    file.truncate()
    file.flush()


@asynccontextmanager
async def request_slot():
    # Uvicorn workers on this host share one Commons allowance, including Retry-After.
    path = Path(tempfile.gettempdir()) / f"longway-commons-{os.getuid()}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "r+") as file:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("The Commons request lock is unavailable.")
        while True:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.1)
        wait = float(file.read() or 0) - time.time()
        if wait > 2:
            raise ValueError("Commons asked us to wait. Try the photograph search later.")
        if wait > 0:
            await asyncio.sleep(wait)
        _postpone(file, 2)
        yield file


async def find(query):
    async with request_slot() as slot:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": query, "gsrlimit": 24, "prop": "imageinfo", "iiurlwidth": 1600,
                "iiprop": "url|size|mime|extmetadata",
            }, headers={"User-Agent": "TheLongWayScout/1.0 (https://thelongway.world; journey photograph research)"})
        _postpone(slot, 2)
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "")
            try:
                seconds = int(retry) if retry.isdecimal() else parsedate_to_datetime(retry).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                seconds = 30
            _postpone(slot, max(2, seconds))
            raise ValueError("Commons asked us to wait. Try the photograph search later.")
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise ValueError("Commons could not complete the photograph search.")
        return candidates(payload)
