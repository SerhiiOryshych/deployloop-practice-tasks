import asyncio
import contextlib

import pytest

from crawler import CrawlConfig, crawl, extract_links, normalize_url, parse_robots
from fakesite import FakeSite

A = "http://site.test"
FAST = dict(per_host_delay=0.0, backoff_base=0.005)


def cfg(**kw):
    return CrawlConfig(**{**FAST, **kw})


def site_with(pages, **kw):
    kw.setdefault("robots", {"site.test": ""})
    return FakeSite(pages, **kw)


# ---------------------------------------------------------------- unit tests
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://Site.TEST/a#top", "http://site.test/a"),
        ("HTTP://site.test:80/a", "http://site.test/a"),
        ("https://site.test:443/a", "https://site.test/a"),
        ("http://site.test", "http://site.test/"),
        ("http://site.test:8080/a?x=1#f", "http://site.test:8080/a?x=1"),
        ("  http://site.test/a  ", "http://site.test/a"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_parse_robots_basic_and_comments():
    text = "# hello\nUser-agent: *\nDisallow: /private  # secret\nDisallow: /tmp/\n"
    assert parse_robots(text) == ["/private", "/tmp/"]


def test_parse_robots_empty_disallow_allows_everything():
    assert parse_robots("User-agent: *\nDisallow:\n") == []


def test_parse_robots_only_star_group_applies():
    text = "User-agent: badbot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin\n"
    assert parse_robots(text) == ["/admin"]


def test_extract_links_resolves_and_filters():
    html = '<a href="/x">1</a><a href="y#z">2</a><a href="mailto:a@b.c">3</a><a>4</a>'
    assert extract_links("http://site.test/dir/page", html) == [
        "http://site.test/x",
        "http://site.test/dir/y#z",
    ]


# ------------------------------------------------------------ crawling basics
def test_crawls_linked_pages(run):
    site = site_with({f"{A}/": ["/a", "/b"], f"{A}/a": ["/c"], f"{A}/b": [], f"{A}/c": []})
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert set(res.pages) == {f"{A}/", f"{A}/a", f"{A}/b", f"{A}/c"}
    assert res.pages[f"{A}/c"] == 2
    assert not res.failed and not res.blocked


def test_each_url_fetched_once_even_with_cycles_and_spelling_variants(run):
    site = site_with(
        {
            f"{A}/": ["/a", "http://SITE.test/a#top", "http://site.test:80/a", "/b"],
            f"{A}/a": ["/", "/b", "/a"],
            f"{A}/b": ["/a", "/"],
        }
    )
    run(crawl([f"{A}/"], site.fetch, cfg()))
    fetched = [u for u in site.requested_urls() if not u.endswith("/robots.txt")]
    assert sorted(fetched) == [f"{A}/", f"{A}/a", f"{A}/b"]


def test_depth_limit(run):
    site = site_with({f"{A}/": ["/1"], f"{A}/1": ["/2"], f"{A}/2": ["/3"], f"{A}/3": []})
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_depth=2)))
    assert set(res.pages) == {f"{A}/", f"{A}/1", f"{A}/2"}
    assert site.count(f"{A}/3") == 0


def test_does_not_leave_the_start_hosts(run):
    site = site_with({f"{A}/": ["http://other.test/x", "/a"], f"{A}/a": []})
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert set(res.pages) == {f"{A}/", f"{A}/a"}
    assert not any("other.test" in u for u in site.requested_urls())


def test_multiple_start_urls_on_two_hosts(run):
    site = FakeSite(
        {"http://a.test/": ["/x"], "http://a.test/x": [], "http://b.test/": ["/y"], "http://b.test/y": []},
        robots={"a.test": "", "b.test": ""},
    )
    res = run(crawl(["http://a.test/", "http://b.test/"], site.fetch, cfg()))
    assert len(res.pages) == 4


# ------------------------------------------------------------ concurrency
def test_max_concurrency_is_respected(run):
    pages = {f"{A}/": [f"/p{i}" for i in range(30)]}
    pages.update({f"{A}/p{i}": [] for i in range(30)})
    site = site_with(pages, latency=0.02)
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_concurrency=3)))
    assert len(res.pages) == 31
    assert 2 <= site.max_in_flight <= 3


def test_per_host_delay_is_respected_under_concurrency(run):
    delay = 0.1
    pages = {f"{A}/": [f"/p{i}" for i in range(8)]}
    pages.update({f"{A}/p{i}": [] for i in range(8)})
    site = site_with(pages)
    run(crawl([f"{A}/"], site.fetch, cfg(max_concurrency=6, per_host_delay=delay)))
    times = site.host_times("site.test")
    assert len(times) >= 9
    gaps = [b - a for a, b in zip(times, times[1:])]
    # Generous margin: an unthrottled crawler has gaps near 0, so half the delay still catches it.
    assert min(gaps) >= delay * 0.5, f"smallest gap {min(gaps):.3f}s, expected about {delay}s"


def test_different_hosts_are_not_throttled_together(run):
    site = FakeSite(
        {"http://a.test/": [], "http://b.test/": []},
        robots={"a.test": "", "b.test": ""},
        latency=0.08,
    )
    run(crawl(["http://a.test/", "http://b.test/"], site.fetch, cfg(per_host_delay=0.02)))
    assert site.max_in_flight == 2


def test_robots_txt_is_fetched_once_per_host(run):
    pages = {f"{A}/": [f"/p{i}" for i in range(10)]}
    pages.update({f"{A}/p{i}": [] for i in range(10)})
    site = site_with(pages, latency=0.02)
    starts = [f"{A}/"] + [f"{A}/p{i}" for i in range(5)]  # many workers hit a new host at once
    run(crawl(starts, site.fetch, cfg(max_concurrency=5)))
    assert site.count(f"{A}/robots.txt") == 1


# ------------------------------------------------------------------ robots
def test_robots_disallow_is_obeyed(run):
    site = site_with(
        {f"{A}/": ["/public", "/private/a", "/private"], f"{A}/public": [], f"{A}/private/a": [], f"{A}/private": []},
        robots={"site.test": "User-agent: *\nDisallow: /private\n"},
    )
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert set(res.pages) == {f"{A}/", f"{A}/public"}
    assert res.blocked == {f"{A}/private/a", f"{A}/private"}
    assert site.count(f"{A}/private/a") == 0


def test_empty_disallow_does_not_block_the_site(run):
    site = site_with({f"{A}/": ["/a"], f"{A}/a": []}, robots={"site.test": "User-agent: *\nDisallow:\n"})
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert set(res.pages) == {f"{A}/", f"{A}/a"}


def test_missing_robots_means_allowed(run):
    site = FakeSite({f"{A}/": ["/a"], f"{A}/a": []})  # robots.txt -> 404
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert len(res.pages) == 2


def test_unreachable_robots_means_crawl_nothing_on_that_host(run):
    site = site_with({f"{A}/": ["/a"], f"{A}/a": []}, errors={f"{A}/robots.txt"})
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_retries=1)), timeout=3)
    assert res.pages == {}
    assert site.count(f"{A}/") == 0


# ------------------------------------------------------------------ retries
def test_retries_5xx_until_success(run):
    site = site_with({f"{A}/": ["/flaky"], f"{A}/flaky": []}, flaky={f"{A}/flaky": 2})
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert f"{A}/flaky" in res.pages
    assert site.count(f"{A}/flaky") == 3


def test_gives_up_after_max_retries(run):
    site = site_with({f"{A}/": ["/bad"]}, always_status={f"{A}/bad": 500})
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_retries=2)))
    assert site.count(f"{A}/bad") == 3
    assert f"{A}/bad" in res.failed and f"{A}/bad" not in res.pages
    assert f"{A}/" in res.pages  # the rest of the crawl still finished


def test_4xx_is_not_retried(run):
    site = site_with({f"{A}/": ["/missing"]})  # unknown page -> 404
    res = run(crawl([f"{A}/"], site.fetch, cfg()))
    assert site.count(f"{A}/missing") == 1
    assert res.failed[f"{A}/missing"] == "HTTP 404"


def test_backoff_grows_exponentially(run):
    base = 0.05
    site = site_with({f"{A}/": ["/flaky"], f"{A}/flaky": []}, flaky={f"{A}/flaky": 3})
    run(crawl([f"{A}/"], site.fetch, cfg(backoff_base=base)))
    t = site.times(f"{A}/flaky")
    gaps = [b - a for a, b in zip(t, t[1:])]
    assert len(gaps) == 3
    # Lower bounds with a 20% margin. Linear or constant backoff fails the last two checks.
    assert gaps[0] >= base * 0.8 and gaps[1] >= 2 * base * 0.8 and gaps[2] >= 4 * base * 0.8


def test_connection_errors_are_retried_and_do_not_hang_the_crawl(run):
    site = site_with({f"{A}/": ["/boom", "/ok"], f"{A}/ok": []}, errors={f"{A}/boom"})
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_retries=2)), timeout=3)
    assert site.count(f"{A}/boom") == 3
    assert f"{A}/boom" in res.failed
    assert set(res.pages) == {f"{A}/", f"{A}/ok"}


def test_many_failures_do_not_exhaust_the_workers(run):
    n = 12
    pages = {f"{A}/": [f"/e{i}" for i in range(n)] + ["/ok"], f"{A}/ok": []}
    site = site_with(pages, errors={f"{A}/e{i}" for i in range(n)})
    res = run(crawl([f"{A}/"], site.fetch, cfg(max_concurrency=2, max_retries=0)), timeout=3)
    assert len(res.failed) == n
    assert f"{A}/ok" in res.pages


# ------------------------------------------------------------------ cancel
def test_cancel_stops_everything_cleanly(run):
    pages = {f"{A}/": [f"/p{i}" for i in range(100)]}
    pages.update({f"{A}/p{i}": [] for i in range(100)})
    site = site_with(pages, latency=0.01)

    async def scenario():
        task = asyncio.create_task(crawl([f"{A}/"], site.fetch, cfg(per_host_delay=0.02)))
        await asyncio.sleep(0.3)  # the full crawl needs more than 2 s, so it is still running
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()
        count = len(site.requests)
        assert 0 < count < 100
        await asyncio.sleep(0.3)
        assert len(site.requests) == count, "requests continued after cancel"
        assert site.in_flight == 0
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert others == [], f"leaked tasks: {others}"

    run(scenario())
