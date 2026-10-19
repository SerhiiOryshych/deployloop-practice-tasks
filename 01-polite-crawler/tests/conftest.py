import asyncio
import os
import sys
from pathlib import Path

import pytest

TASK_DIR = Path(__file__).resolve().parent.parent
USING_SOLUTION = os.environ.get("DEPLOYLOOP_SOLUTION") == "1"

sys.path.insert(0, str(TASK_DIR))
if USING_SOLUTION:
    if not (TASK_DIR / "solution" / "crawler.py").exists():
        pytest.exit("DEPLOYLOOP_SOLUTION=1 but solution/ is not present.")
    sys.path.insert(0, str(TASK_DIR / "solution"))


def pytest_report_header(config):
    return f"deployloop: testing {'SOLUTION' if USING_SOLUTION else 'STARTER'} crawler.py"


def run(coro, timeout: float = 10.0):
    """Run a coroutine in a fresh event loop; leaked tasks are cancelled at exit."""
    async def main():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(main())


@pytest.fixture(name="run")
def run_fixture():
    return run
