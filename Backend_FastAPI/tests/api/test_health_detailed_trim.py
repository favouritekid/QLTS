"""PR1 Commit 6 anchor: /health/detailed response is trimmed to an up/down
boolean per dependency — no exception class names, worker counts, or other
internal detail that aids reconnaissance from this public endpoint (A02 / A09).
``/health`` (the Docker/nginx healthcheck target) stays unchanged.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_detailed_no_internal_leak(client: AsyncClient):
    resp = await client.get("/health/detailed")
    # 200 when all deps up, 503 when any down (Celery has no worker in tests).
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    for dep in ("api", "database", "redis_cache", "celery_broker"):
        assert dep in body, f"missing dependency {dep}"
        # Each check must expose ONLY a status — no message / exception class /
        # worker count.
        assert set(body[dep].keys()) == {"status"}, (
            f"{dep} leaks extra keys: {body[dep]}"
        )
        assert body[dep]["status"] in ("up", "down")


@pytest.mark.asyncio
async def test_health_simple_unchanged(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
