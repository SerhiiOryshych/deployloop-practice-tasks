# DeployLoop free practice tasks

Two original, free practice tasks for engineers preparing for forward-deployed
engineer (FDE), applied-AI and AI-security interviews. They are written by the
DeployLoop project. They are not copied from, and not affiliated with, any
company's interview. No company name is implied.

| Task | Skill it trains | Time box |
|---|---|---|
| [01-polite-crawler](01-polite-crawler/) | asyncio concurrency, politeness, retries, cancellation | 60-90 min |
| [02-mcp-tool-wrapper](02-mcp-tool-wrapper/) | tool design, validation, secrets, timeouts, prompt-injection-safe output (stretch) | 90-120 min |

Each task is a starter implementation that runs but is incomplete and buggy,
plus tests that fail until you fix it. Everything runs locally. There is no
network access and no real service.

## Setup

Python 3.11 or newer.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cd 01-polite-crawler && pytest      # starts red
```

Rules for a fair attempt: do not edit `tests/` or the fake service files
(`fakesite.py`, `fake_ticket_api.py`); set a timer; write down what you would do
with more time; then answer the follow-up questions in each README out loud.

## About a reference solution

The reference solutions are not published. If you keep your own solution in a
`solution/` folder, `DEPLOYLOOP_SOLUTION=1 pytest` runs the tests against it.

More practice tasks and the interview vault: https://deploy-loop.vercel.app/?v=a&utm_source=gh_org_repo

## License

MIT, see [LICENSE](LICENSE).
