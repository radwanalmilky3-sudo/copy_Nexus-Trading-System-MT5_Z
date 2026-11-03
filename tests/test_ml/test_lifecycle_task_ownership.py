import asyncio

import pytest

from services.nexus_ml.main import _cancel_lifecycle_tasks


@pytest.mark.asyncio
async def test_lifecycle_shutdown_cancels_and_awaits_all_owned_tasks():
    started = asyncio.Event()

    async def worker():
        started.set()
        await asyncio.Event().wait()

    tasks = [asyncio.create_task(worker()) for _ in range(3)]
    await started.wait()

    await _cancel_lifecycle_tasks(*tasks)

    assert all(task.done() and task.cancelled() for task in tasks)


@pytest.mark.asyncio
async def test_lifecycle_shutdown_ignores_unstarted_optional_task():
    task = asyncio.create_task(asyncio.sleep(60))
    await _cancel_lifecycle_tasks(None, task)

    assert task.done() and task.cancelled()
