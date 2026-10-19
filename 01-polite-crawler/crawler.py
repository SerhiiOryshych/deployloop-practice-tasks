"""Polite concurrent crawler - STARTER.

It runs, and it works on a happy path. It is also incomplete and has bugs.
Make `pytest` pass without editing tests/ or fakesite.py. Keep it asyncio-only
(no extra dependencies).

Brief (see README.md for the full text):
  * at most `max_concurrency` requests in flight at once (all hosts together)
  * at least `per_host_delay` seconds between two request starts to one host
  * obey robots.txt (`User-agent: *` groups, `Disallow:` prefixes)
  * every URL is fetched at most once (after normalization)
  * stop following links deeper than `max_depth`
  * retry 5xx and connection errors with exponential backoff
  * only crawl hosts that appear in `start_urls`
  * cancelling `crawl()` must stop everything cleanly
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit


@dataclass
class CrawlConfig:
    max_concurrency: int = 4
    per_host_delay: float = 0.05  # seconds between request starts to the same host
    max_depth: int = 3  # start URLs have depth 0
    max_retries: int = 3  # retries after the first attempt (so up to 4 attempts)
    backoff_base: float = 0.05  # sleep backoff_base * 2**attempt before a retry


@dataclass
class CrawlResult:
    pages: dict[str, int] = field(default_factory=dict)  # url -> depth, status 200 only
    failed: dict[str, str] = field(default_factory=dict)  # url -> reason
    blocked: set[str] = field(default_factory=set)  # urls skipped because of robots.txt


Fetch = Callable[[str], Awaitable[object]]  # returns an object with .status and .text


def normalize_url(url: str) -> str:
    # TODO(candidate): two spellings of the same page must give the same string.
    # Think: scheme/host case, default ports, empty path, fragments.
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def parse_robots(text: str) -> list[str]:
    """Return the Disallow path prefixes that apply to us (`User-agent: *`)."""
    # TODO(candidate): handle comments, groups and empty values properly.
    rules = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "disallow":
            rules.append(value.strip())
    return rules


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def extract_links(base_url: str, html: str) -> list[str]:
    """Absolute http(s) links found in `html` (provided; you may keep it as is)."""
    parser = _LinkParser()
    parser.feed(html)
    out = []
    for href in parser.hrefs:
        absolute = urljoin(base_url, href.strip())
        if urlsplit(absolute).scheme in ("http", "https"):
            out.append(absolute)
    return out


async def crawl(
    start_urls: list[str], fetch: Fetch, config: CrawlConfig | None = None
) -> CrawlResult:
    config = config or CrawlConfig()
    result = CrawlResult()
    queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    seen: set[str] = set()
    robots_cache: dict[str, list[str]] = {}  # netloc -> disallow prefixes
    last_request: dict[str, float] = {}  # netloc -> monotonic time of last request start
    allowed_hosts = {urlsplit(normalize_url(u)).netloc for u in start_urls}

    def enqueue(url: str, depth: int) -> None:
        # TODO(candidate): stay inside `allowed_hosts`.
        url = normalize_url(url)
        if url in seen:
            return
        seen.add(url)
        queue.put_nowait((url, depth))

    async def polite_fetch(url: str):
        host = urlsplit(url).netloc
        wait = last_request.get(host, 0.0) + config.per_host_delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        last_request[host] = time.monotonic()
        return await fetch(url)

    async def fetch_with_retries(url: str):
        # TODO(candidate): retry 5xx and ConnectionError with exponential backoff.
        # 4xx must not be retried. After the last retry, report failure.
        return await polite_fetch(url)

    async def get_rules(url: str) -> list[str]:
        parts = urlsplit(url)
        if parts.netloc not in robots_cache:
            resp = await polite_fetch(f"{parts.scheme}://{parts.netloc}/robots.txt")
            robots_cache[parts.netloc] = parse_robots(resp.text) if resp.status == 200 else []
        return robots_cache[parts.netloc]

    async def worker() -> None:
        while True:
            url, depth = await queue.get()
            rules = await get_rules(url)
            path = urlsplit(url).path
            if any(path.startswith(prefix) for prefix in rules):
                result.blocked.add(url)
            else:
                resp = await fetch_with_retries(url)
                if resp.status == 200:
                    result.pages[url] = depth
                    if depth < config.max_depth:
                        for link in extract_links(url, resp.text):
                            enqueue(link, depth + 1)
                else:
                    result.failed[url] = f"HTTP {resp.status}"
            queue.task_done()

    for u in start_urls:
        enqueue(u, 0)
    workers = [asyncio.create_task(worker()) for _ in range(config.max_concurrency)]
    await queue.join()
    for w in workers:
        w.cancel()
    return result
