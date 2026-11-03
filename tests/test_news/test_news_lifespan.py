"""Exercise the real lifespan with isolated resources and no service imports."""
import ast
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("failure", ["body", "initialize", "close", "cancel", None])
def test_lifespan_releases_resources_and_owns_tasks_per_start(failure):
    source = Path(__file__).resolve().parents[2] / "services/nexus_news/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    lifespan = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    resources = []
    stopped = []
    runs = []

    class Resource:
        def __init__(self, *args, **kwargs):
            self.closed = False
            resources.append(self)

        async def initialize(self):
            if failure == "initialize":
                raise RuntimeError("initialize")

        async def close(self):
            assert all(task.done() for tasks in runs for task in tasks)
            self.closed = True
            if failure == "close" and resources.index(self) % 4 == 1:
                raise RuntimeError("close")

        aclose = close

        async def official_source_loop(self):
            await worker()

    async def worker():
        try:
            await asyncio.Future()
        finally:
            stopped.append(asyncio.current_task())

    namespace = dict(
        asyncio=asyncio, AsyncExitStack=AsyncExitStack,
        asynccontextmanager=asynccontextmanager, FastAPI=object,
        log=SimpleNamespace(info=lambda *a, **k: None),
        aioredis=SimpleNamespace(from_url=Resource),
        NewsFetcher=Resource, CalendarParser=Resource,
        SocialSentiment=lambda **kwargs: object(), FundamentalRuntime=Resource,
        REDIS_URL="unused", NEWSAPI_KEY="", GNEWS_KEY="", USE_FINBERT=False,
        _bg_tasks=[], _news_poll_loop=worker, _calendar_poll_loop=worker,
        _heartbeat_loop=worker,
    )
    exec(compile(ast.Module(body=[lifespan], type_ignores=[]), str(source), "exec"), namespace)

    async def exercise():
        previous = None
        for _ in range(2):
            start = len(resources)
            try:
                async with namespace["lifespan"](None):
                    tasks = namespace["_bg_tasks"]
                    assert tasks is not previous
                    assert len(tasks) == 4
                    runs.append(tuple(tasks))
                    previous = tasks
                    await asyncio.sleep(0)
                    if failure == "body":
                        raise RuntimeError("body")
                    if failure == "cancel":
                        raise asyncio.CancelledError()
            except (RuntimeError, asyncio.CancelledError) as exc:
                assert failure is not None
                assert str(exc) == ("" if failure == "cancel" else failure)
            else:
                assert failure is None
            assert namespace["_bg_tasks"] == []
            assert all(resource.closed for resource in resources[start:])
            assert all(task.done() for tasks in runs for task in tasks)
        assert len(stopped) == (0 if failure == "initialize" else 8)

    asyncio.run(exercise())
