import asyncio

import pytest

from services.nexus_ml import traders_api


@pytest.mark.asyncio
async def test_traders_shutdown_cancels_and_awaits_owned_tasks():
    started = asyncio.Event()

    async def worker():
        started.set()
        await asyncio.Event().wait()

    tasks = [asyncio.create_task(worker()) for _ in range(2)]
    await started.wait()

    await traders_api._cancel_and_wait_tasks(*tasks)

    assert all(task.done() and task.cancelled() for task in tasks)


@pytest.mark.asyncio
async def test_scheduler_stop_joins_its_cancelled_loop(monkeypatch):
    started = asyncio.Event()

    async def scheduler_loop():
        started.set()
        await asyncio.Event().wait()

    class SchedulerStub:
        def __init__(self):
            self._task = asyncio.create_task(scheduler_loop())

        def stop(self):
            self._task.cancel()

    scheduler = SchedulerStub()
    monkeypatch.setattr(traders_api, "_retrain_scheduler", scheduler)
    await started.wait()

    await traders_api._stop_retrain_scheduler()

    assert scheduler._task.done() and scheduler._task.cancelled()
    assert traders_api._retrain_scheduler is None
