"""Freely licensed Commons photographs, with credit taken from the file metadata."""
import asyncio
import base64
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime
import fcntl
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import stat
import tempfile
import time

import httpx
from llm.vision import image_block


_FREE = re.compile(r"CC0(?: 1\.0)?|public domain|CC BY(?:-SA)?(?: \d+(?:\.\d+)?)?", re.I)
_USER_AGENT = "TheLongWayScout/1.0 (https://thelongway.world; journey photograph research)"
_COPY_LIMIT = 400 * 1024
# Where Commons serves image bytes. A live search on 2026-11-21 returned every thumbnail from thumb.wikimedia.org;
# with only upload.wikimedia.org allowed, no copy was ever fetched and the Scout always chose blind.
_COPY_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}
_SIGNATURES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}


class _MetadataText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _field(metadata, key):
    parser = _MetadataText()
    parser.feed(metadata.get(key, {}).get("value") or "")
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def candidates(payload):
    found = []
    for page in payload.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            meta = info.get("extmetadata", {})

            licence, author = _field(meta, "LicenseShortName"), _field(meta, "Artist")
            width = info.get("width", 0)
            if (not author or not _FREE.fullmatch(licence) or width < 1200
                    or info.get("thumbwidth", width) < 1200 or not info.get("thumburl")
                    or not info.get("descriptionurl") or not info.get("mime", "").startswith("image/")):
                continue
            found.append(dict(title=page["title"], page=info["descriptionurl"], url=info["thumburl"],
                              author=author, licence=licence, licence_url=_field(meta, "LicenseUrl") or None,
                              description=_field(meta, "ImageDescription")[:300].rstrip(),
                              date=_field(meta, "DateTimeOriginal") or None,
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


async def _imageinfo(client, **params):
    async with request_slot() as slot:
        response = await client.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "prop": "imageinfo", **params})
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
        return payload


async def find(query):
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _USER_AGENT}) as client:
        payload = await _imageinfo(client, generator="search", gsrnamespace=6, gsrsearch=query,
            gsrlimit=24, iiurlwidth=1600, iiprop="url|size|mime|extmetadata",
            iiextmetadatafilter="Artist|LicenseShortName|LicenseUrl|ImageDescription|DateTimeOriginal")
    return candidates(payload)


async def _download(client, url):
    target = httpx.URL(url)
    if target.scheme != "https" or target.host not in _COPY_HOSTS:
        return None
    async with client.stream("GET", target, headers={"Accept-Encoding": "identity"}) as response:
        response.raise_for_status()
        mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        if mime not in _SIGNATURES or int(response.headers.get("content-length", 0)) > _COPY_LIMIT:
            return None
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16384):
            if len(data) + len(chunk) > _COPY_LIMIT:
                return None
            data.extend(chunk)
        if data.startswith(_SIGNATURES[mime]):
            return image_block(mime, base64.b64encode(data).decode("ascii"))
    return None


async def small_copies(found):
    """Keep original candidate numbers, including gaps when Commons cannot serve a copy."""
    blocks = {}
    try:
        async with asyncio.timeout(25), httpx.AsyncClient(timeout=5, headers={"User-Agent": _USER_AGENT}) as client:
            payload = await _imageinfo(client, titles="|".join(p["title"] for p in found),
                                       iiurlwidth=500, iiurlheight=500, iiprop="url")
            urls = {page["title"]: info["thumburl"] for page in payload.get("query", {}).get("pages", {}).values()
                    for info in page.get("imageinfo", []) if info.get("thumburl") and 0 < info.get("thumbwidth", 0) <= 500}
            for number, photo in enumerate(found, 1):
                if url := urls.get(photo["title"]):
                    if number > 1:
                        await asyncio.sleep(0.3)
                    try:
                        block = await _download(client, url)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 429:
                            break
                        continue
                    except (httpx.HTTPError, ValueError):
                        continue
                    if block:
                        blocks[number] = block
    except (TimeoutError, httpx.HTTPError, ValueError):
        pass  # Even a batch timeout keeps copies already received.
    return blocks
