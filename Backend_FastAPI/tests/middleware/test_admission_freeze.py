# tests/middleware/test_admission_freeze.py
"""T0-2 admission freeze middleware coverage.

Uses a stub FastAPI app with the same prefix shapes as the 4 admission routers
(verified at branch ``feat/admission-full-cutover`` HEAD ``2c57e5d6``: 4 router
files share 3 prefixes — ``/api/admissions``, ``/api/admission-config``,
``/api/public/admissions``). Stubbing keeps these tests free of DB/Casbin/Redis
and lets us exhaustively cover the method × prefix × frozen-state matrix.

The middleware reads ``settings.ADMISSION_FROZEN`` directly per request, so we
toggle the singleton and rely on the existing module import.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings as app_settings
from app.middleware.admission_freeze import (
    FROZEN_METHODS,
    FROZEN_PREFIXES,
    AdmissionFreezeMiddleware,
)


def _make_stub_app() -> FastAPI:
    """Build an isolated app whose routes shadow the real admission prefixes."""
    app = FastAPI()
    app.add_middleware(AdmissionFreezeMiddleware)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    @app.api_route("/api/admissions/{rest:path}", methods=methods)
    async def admissions_stub(rest: str):
        return {"ok": True, "scope": "admissions", "rest": rest}

    @app.api_route("/api/admission-config/{rest:path}", methods=methods)
    async def admission_config_stub(rest: str):
        return {"ok": True, "scope": "admission-config", "rest": rest}

    @app.api_route("/api/public/admissions/{rest:path}", methods=methods)
    async def public_admissions_stub(rest: str):
        return {"ok": True, "scope": "public-admissions", "rest": rest}

    @app.api_route("/api/leads/{rest:path}", methods=methods)
    async def leads_stub(rest: str):
        return {"ok": True, "scope": "leads"}

    @app.get("/health")
    async def health_stub():
        return {"ok": True}

    @app.api_route("/api/admissionsfoo", methods=methods)
    async def lookalike_stub():
        # Confirms path-segment matching: /api/admissionsfoo is NOT under /api/admissions.
        return {"ok": True, "scope": "lookalike"}

    return app


@pytest.fixture
def stub_app() -> FastAPI:
    return _make_stub_app()


@pytest.fixture
async def client(stub_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=stub_app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def freeze_off():
    original = app_settings.ADMISSION_FROZEN
    app_settings.ADMISSION_FROZEN = False
    try:
        yield
    finally:
        app_settings.ADMISSION_FROZEN = original


@pytest.fixture
def freeze_on():
    original = app_settings.ADMISSION_FROZEN
    app_settings.ADMISSION_FROZEN = True
    try:
        yield
    finally:
        app_settings.ADMISSION_FROZEN = original


# ---------------------------------------------------------------------------
# Contract sanity (data shape only — NOT a drift catch).
# ---------------------------------------------------------------------------


def test_freeze_constants_have_expected_shape():
    assert isinstance(FROZEN_PREFIXES, tuple)
    assert len(FROZEN_PREFIXES) >= 1
    assert all(p.startswith("/api/") for p in FROZEN_PREFIXES)
    assert FROZEN_METHODS == frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ---------------------------------------------------------------------------
# Real drift catch: scan the live route table on `fastapi_app` and assert
# that every registered admission path is under some FROZEN_PREFIX. This
# fires when:
#   - an existing admission router's prefix is renamed,
#   - a new admission router is added (and mounted) without updating
#     FROZEN_PREFIXES,
#   - an admission-named endpoint is added under a non-admission router.
# Because it iterates the actual route table — not a fixed import list — it
# does NOT need to be edited when admission routers come or go.
# ---------------------------------------------------------------------------


def test_no_admission_route_escapes_freeze_coverage():
    # Importing `fastapi_app` triggers `include_router(...)` for every router
    # registered in main.py and populates `fastapi_app.routes`. Lifespan does
    # not run on import, so this stays a unit-style test (no DB / no Redis).
    from app.main import fastapi_app

    admission_paths: set[str] = set()
    for route in fastapi_app.routes:
        path = getattr(route, "path", "")
        if not isinstance(path, str) or not path.startswith("/api/"):
            continue
        # Substring "admission" matches `/api/admissions`, `/api/admission-config`,
        # `/api/public/admissions`, and any future admission surface. It does NOT
        # match `/api/admin/...` (different word).
        if "admission" not in path.lower():
            continue
        admission_paths.add(path)

    assert admission_paths, (
        "Route-table scan returned no admission paths. Either main.py stopped "
        "registering admission routers, or the heuristic is broken — investigate "
        "before trusting this test."
    )

    def _under_some_freeze_prefix(path: str) -> bool:
        return any(path == fp or path.startswith(fp + "/") for fp in FROZEN_PREFIXES)

    uncovered = sorted(p for p in admission_paths if not _under_some_freeze_prefix(p))
    assert not uncovered, (
        f"Admission route(s) not covered by FROZEN_PREFIXES: {uncovered}. "
        f"Update Backend_FastAPI/app/middleware/admission_freeze.py FROZEN_PREFIXES "
        f"and Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md §3.5 + §6.2 to match."
    )

    def _matches_some_route(prefix: str) -> bool:
        return any(p == prefix or p.startswith(prefix + "/") for p in admission_paths)

    spurious = sorted(fp for fp in FROZEN_PREFIXES if not _matches_some_route(fp))
    assert not spurious, (
        f"FROZEN_PREFIXES contains entries with no matching admission route: "
        f"{spurious}. Stale freeze coverage — remove from FROZEN_PREFIXES."
    )


# ---------------------------------------------------------------------------
# ADMISSION_FROZEN=False  →  every method passes through the freeze gate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_writes_pass_through_when_unfrozen(client, freeze_off, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 200, (
        f"unfrozen {method} {prefix}/anything should pass through, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# ADMISSION_FROZEN=True  →  writes blocked on the 3 admission prefixes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_writes_blocked_when_frozen(client, freeze_on, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 503, (
        f"frozen {method} {prefix}/anything should return 503, "
        f"got {response.status_code} {response.text!r}"
    )
    body = response.json()
    assert body["code"] == "ADMISSION_FROZEN"
    assert body["frozen_prefix"] == prefix
    assert "frozen for maintenance" in body["detail"]


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
@pytest.mark.asyncio
async def test_reads_allowed_when_frozen(client, freeze_on, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 200, (
        f"frozen {method} {prefix}/anything must be allowed, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# Frozen window leaves non-admission traffic untouched.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_non_admission_writes_unaffected(client, freeze_on, method):
    response = await client.request(method, "/api/leads/123")
    assert response.status_code == 200
    assert response.json()["scope"] == "leads"


@pytest.mark.asyncio
async def test_health_endpoint_still_reachable(client, freeze_on):
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_path_segment_match_rejects_lookalike(client, freeze_on, method):
    # /api/admissionsfoo string-startswith /api/admissions but is NOT under it.
    response = await client.request(method, "/api/admissionsfoo")
    assert response.status_code == 200, (
        f"frozen {method} /api/admissionsfoo must NOT match prefix /api/admissions, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# Bare prefix (no trailing slash) is also covered.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.asyncio
async def test_bare_prefix_post_blocked(client, freeze_on, prefix):
    # FastAPI route is `/{prefix}/{rest:path}` so a bare prefix returns 404
    # under the stub, but that 404 must come from the router AFTER the
    # freeze gate decides — frozen state should produce a 503 first.
    response = await client.post(prefix)
    assert response.status_code == 503
    body = response.json()
    assert body["frozen_prefix"] == prefix
