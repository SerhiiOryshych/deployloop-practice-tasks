# Task 1: polite concurrent crawler

Time box: **60-90 minutes**. Python 3.11+, standard library only (plus pytest).

## The brief

Your team runs a crawler that checks customer documentation sites before an
integration go-live. A first version exists in `crawler.py`. It works on small
happy-path sites, but on real sites it hammers hosts, fetches pages twice,
hangs, and keeps running after you cancel it.

Fix and finish `crawler.py` so that all tests in `tests/` pass.

Requirements:

1. At most `max_concurrency` requests in flight at the same time.
2. At least `per_host_delay` seconds between two request starts to the same
   host. This also applies to `robots.txt` requests and retries. Different
   hosts must not slow each other down.
3. Obey `robots.txt` (only `User-agent: *` groups; `Disallow:` path prefixes;
   empty `Disallow:` allows everything; comments allowed). Fetch it once per
   host. Missing (4xx) means allowed. Unreachable (5xx or connection error after
   retries) means: crawl nothing on that host.
4. Every page is fetched at most once. Different spellings of one URL are one
   URL (case of scheme and host, default ports, fragments, empty path).
5. `max_depth`: start URLs are depth 0; do not follow links from pages at
   `max_depth`.
6. Retry 5xx and connection errors up to `max_retries` times with exponential
   backoff `backoff_base * 2**attempt`. Never retry 4xx. A page that still
   fails is reported in `result.failed`; the rest of the crawl continues.
7. Only crawl hosts that appear in `start_urls`.
8. Cancelling the `crawl()` task stops all work: no leaked tasks, no new
   requests afterwards.

There is no network. `fakesite.py` is an in-process fake site. Your `fetch`
function is `site.fetch`. Read it first, it records what you do.

Run: `pytest -q` (or `pytest -q -x -k delay` while working).
The starter suite takes about 10 s, because the tests that hang on the buggy
starter run until their timeout. A correct solution finishes much faster.
Optional: if you keep your own solution in a `solution/` folder,
`DEPLOYLOOP_SOLUTION=1 pytest` tests it.

## What "good" looks like

- All tests pass, repeatedly (run them 10 times; no flakiness).
- The fixes are small and you can explain each bug in one sentence: what
  interleaving of tasks causes it, and why the fix removes it.
- Check-then-act sequences that span an `await` are done atomically (lock, or
  publish a Future before awaiting).
- Every queue item gets `task_done()` on every path (`try/finally`).
- Workers are cancelled and awaited in a `finally` block.
- You did not add a global lock or a sleep "to be safe".
- You wrote down limits: what happens with a 10 GB response, a redirect loop,
  a link to an HTML page that is 200 MB.

Signals of a weak attempt: tests pass only with larger sleeps; swallowing all
exceptions silently; polling loops instead of events; `time.sleep` in async code.

## Interviewer follow-up questions

Scaling
1. This crawler must now do 50 million URLs a day across 20,000 hosts. What
   breaks first in a single process? How do you shard the work (by host?) and
   why does sharding by host make politeness easier?
2. Where does the "seen" set live at that size? Compare an in-memory set, a
   Bloom filter and a database. What false positives can you accept?
3. How do you resume after a crash without re-fetching everything?

Backpressure
4. A slow host holds several workers in its per-host lock while other hosts
   wait for free workers. What is the failure mode? Design a per-host queue or
   a scheduler that fixes it.
5. The queue is unbounded. A page with 100,000 links arrives. What do you do?
   Where do you apply backpressure, and what do you drop first?
6. How would you add a per-request timeout and a total deadline? What should
   cancellation of one request do to its siblings?

Observability
7. Which metrics would you export? (requests by status class, retry count,
   queue depth, in-flight, per-host delay actually achieved, robots cache hit
   rate.) Which one do you alert on?
8. How do you debug "the crawl finished but 3,000 pages are missing"?
   What do you log per URL so that this is answerable?
9. How would you test politeness in CI without real sleeps (fake clock)?

Correctness and ethics
10. How do you honor `Retry-After`, `Crawl-delay`, and `Allow:` rules? How do
    you identify yourself (User-Agent) and give site owners a way to contact you?
11. Redirects, `<base href>`, `rel=nofollow`, canonical links, infinite
    calendars and session-id URLs: which do you handle and how?
