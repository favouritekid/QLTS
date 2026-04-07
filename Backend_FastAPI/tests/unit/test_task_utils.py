import logging

import pytest


def test_run_async_task_reuses_worker_loop_for_loop_bound_resources():
    """
    Celery tasks keep async clients alive across task boundaries.

    A per-call asyncio.run() closes the loop after every task, which breaks
    those reused clients on the next task. This test models a loop-bound
    resource and ensures the helper keeps using the same worker loop.
    """
    from app.tasks.utils import _close_task_event_loop, run_async_task

    class LoopBoundResource:
        def __init__(self) -> None:
            self.bound_loop = None
            self.calls = 0

        async def use(self) -> dict:
            import asyncio

            loop = asyncio.get_running_loop()
            if self.bound_loop is None:
                self.bound_loop = loop
            elif loop is not self.bound_loop:
                raise RuntimeError("resource rebound to a different loop")

            self.calls += 1
            return {"status": "ok", "call": self.calls}

    resource = LoopBoundResource()
    task_log = logging.getLogger("test_task_utils")

    try:
        first = run_async_task(
            async_func=resource.use,
            task_name="loop_reuse_first",
            task_log=task_log,
            validate_keys=["status", "call"],
        )
        second = run_async_task(
            async_func=resource.use,
            task_name="loop_reuse_second",
            task_log=task_log,
            validate_keys=["status", "call"],
        )
    finally:
        _close_task_event_loop()

    assert first["call"] == 1
    assert second["call"] == 2
    assert resource.bound_loop is not None


@pytest.mark.asyncio
async def test_run_async_task_supports_callers_with_existing_event_loop():
    """Async test harnesses should still be able to invoke Celery helpers."""
    from app.tasks.utils import _close_task_event_loop, run_async_task

    async def sample() -> dict:
        return {"status": "ok", "delivery_id": 123}

    try:
        result = run_async_task(
            async_func=sample,
            task_name="existing_loop",
            task_log=logging.getLogger("test_task_utils"),
            validate_keys=["status", "delivery_id"],
        )
    finally:
        _close_task_event_loop()

    assert result == {"status": "ok", "delivery_id": 123}
