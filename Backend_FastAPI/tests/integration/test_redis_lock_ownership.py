"""acquire_redis_lock must only ever release the lock it actually holds.

The release used to be a bare DELETE on the key. That is fine while nothing
overruns its TTL, and wrong the moment something does: the late holder deletes
whatever is at the key — including a lock a DIFFERENT worker has since taken —
and a third worker walks straight in. The failure is invisible, because every
call still returns success.
"""
import asyncio

import pytest

from app.utils import redis_lock as rl

pytestmark = pytest.mark.asyncio

KEY = "test_lock_ownership"
RKEY = f"lock:{KEY}"


@pytest.fixture(autouse=True)
async def _clean():
    client = rl.get_redis_client()
    await client.delete(RKEY)
    yield
    await client.delete(RKEY)


class TestOwnershipRelease:
    async def test_lock_is_released_when_still_owned(self):
        client = rl.get_redis_client()
        async with rl.acquire_redis_lock(KEY, timeout=30) as acquired:
            assert acquired
            assert await client.get(RKEY) is not None
        assert await client.get(RKEY) is None, "lock not released by its owner"

    async def test_stale_owner_does_not_delete_the_new_holders_lock(self):
        """The exact overlap scenario: holder A overruns, its key expires, B
        acquires, then A finishes. A must leave B's lock alone."""
        client = rl.get_redis_client()

        async with rl.acquire_redis_lock(KEY, timeout=30) as acquired_a:
            assert acquired_a
            # Simulate A's TTL lapsing and B taking the lock in the meantime.
            await client.delete(RKEY)
            await client.set(RKEY, "owner-B-token", ex=30)
        # Leaving A's context runs A's release.
        still_there = await client.get(RKEY)
        assert still_there is not None, "stale owner deleted the new holder's lock"
        value = still_there.decode() if isinstance(still_there, bytes) else still_there
        assert value == "owner-B-token"

    async def test_two_holders_cannot_overlap(self):
        async with rl.acquire_redis_lock(KEY, timeout=30) as first:
            assert first
            async with rl.acquire_redis_lock(
                KEY, timeout=30, max_retries=1, retry_delay=0.01
            ) as second:
                assert second is False or second is None, (
                    "a second holder got the lock while the first held it"
                )

    async def test_lock_value_is_unique_per_acquisition(self):
        """A timestamp-shaped value is not unique across processes, so it cannot
        prove ownership. Two acquisitions must never produce the same value."""
        client = rl.get_redis_client()
        seen = set()
        for _ in range(3):
            async with rl.acquire_redis_lock(KEY, timeout=30) as acquired:
                assert acquired
                raw = await client.get(RKEY)
                seen.add(raw.decode() if isinstance(raw, bytes) else raw)
            await asyncio.sleep(0)
        assert len(seen) == 3, f"lock values repeated: {seen}"
