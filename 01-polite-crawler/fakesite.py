"""In-process fake web site used by the tests. Do not edit.

It plays the role of "the internet": `await site.fetch(url)` returns a
`Response`, or raises ConnectionError for URLs listed in `errors`. It records
every request so tests can check concurrency, politeness and retries.
No sockets are opened.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from html import escape
from urllib.parse import urlsplit


@dataclass
class Response:
    status: int
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class FakeSite:
    def __init__(
        self,
        pages: dict[str, list[str] | str] | None = None,
        *,
        robots: dict[str, str] | None = None,  # netloc -> robots.txt text
        latency: float = 0.005,
        flaky: dict[str, int] | None = None,  # url -> number of initial 503 answers
        errors: set[str] | None = None,  # urls that raise ConnectionError
        always_status: dict[str, int] | None = None,  # url -> fixed status
    ) -> None:
        self.pages = dict(pages or {})
        self.robots = dict(robots or {})
        self.latency = latency
        self.flaky = dict(flaky or {})
        self.errors = set(errors or ())
        self.always_status = dict(always_status or {})
        self.requests: list[tuple[float, str]] = []  # (monotonic start time, url)
        self.in_flight = 0
        self.max_in_flight = 0

    # ---- helpers for tests -------------------------------------------------
    def count(self, url: str) -> int:
        return sum(1 for _, u in self.requests if u == url)

    def times(self, url: str) -> list[float]:
        return [t for t, u in self.requests if u == url]

    def host_times(self, netloc: str) -> list[float]:
        return sorted(t for t, u in self.requests if urlsplit(u).netloc == netloc)

    def requested_urls(self) -> list[str]:
        return [u for _, u in self.requests]

    # ---- the fake network ----------------------------------------------------
    async def fetch(self, url: str) -> Response:
        self.requests.append((time.monotonic(), url))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.latency)
            if url in self.errors:
                raise ConnectionError(f"connection reset: {url}")
            if url in self.always_status:
                return Response(self.always_status[url])
            if self.count(url) <= self.flaky.get(url, 0):
                return Response(503)
            parts = urlsplit(url)
            if parts.path == "/robots.txt":
                text = self.robots.get(parts.netloc)
                return Response(200, text) if text is not None else Response(404)
            body = self.pages.get(url)
            if body is None:
                return Response(404)
            if isinstance(body, list):
                links = "".join(f'<li><a href="{escape(h)}">link</a></li>' for h in body)
                body = f"<html><body><p>page</p><a name='x'>no href</a><ul>{links}</ul></body></html>"
            return Response(200, body, {"content-type": "text/html"})
        finally:
            self.in_flight -= 1
