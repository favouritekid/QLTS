"""Anchor: Casbin policy paths align với actual FastAPI route mounts.

Post-QA-E2E findings 2026-05-16 (W2-2 + W2-3) anchor — prevent re-drift
khi developer thêm policy entry mới mà không kiểm tra route exists.

Non-tautological: query DB live policies + check against FastAPI route
table (read from main.py-imported `app.routes`). Khác với template parity
test (compare template dict to template dict), test này check **runtime
route table** vs **runtime DB policies**.

History:
- W2-2 cleanup 4 dead `/api/refunds/*` ALLOW entries (refunds module
  deferred per `finance-event-decisions` memory).
- W2-3 fix MANAGER /api/leads/export — was 2 wrong sub-paths (/csv +
  /excel), now 1 correct query-param endpoint.

Re-introducing a Casbin entry pointing to a 404 route should make this
test fail loudly.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    MANAGER_TEMPLATE,
)
from app.database import AsyncSessionLocal
from app.main import fastapi_app


def _collect_route_paths() -> set[str]:
    """Collect actual FastAPI route paths (path param names included)."""
    paths: set[str] = set()
    for route in fastapi_app.routes:
        # Skip non-HTTP routes (websockets, mounts)
        if hasattr(route, "path") and getattr(route, "methods", None):
            paths.add(route.path)
    return paths


def _accountant_objects() -> set[str]:
    return {p["object"] for p in ACCOUNTANT_TEMPLATE["policies"]}


def _manager_export_entries() -> set[tuple[str, str]]:
    return {
        (p["object"], p["action"])
        for p in MANAGER_TEMPLATE["policies"]
        if p["object"].startswith("/api/leads/export")
    }


def test_refunds_policy_entries_present_in_accountant_template():
    """Finance Phase 1 anchor: refund router shipped, so policy must exist."""
    objects = _accountant_objects()
    expected = {"/api/refunds", "/api/refunds/{id}", "/api/refunds/{id}/process"}
    missing = expected - objects
    assert not missing, (
        f"ACCOUNTANT_TEMPLATE missing refund policies: {sorted(missing)}"
    )


def test_leads_export_template_matches_actual_route():
    """W2-3 anchor: /api/leads/export Casbin path khớp router actual path.

    Router định nghĩa single endpoint `/api/leads/export` với query
    param `?format=csv|excel|json` (leads.py:315). Casbin TỪNG sai 2
    entry `/api/leads/export/csv` + `/api/leads/export/excel` → 404 silent.

    Verify:
    1. /api/leads/export route exists trong FastAPI route table
    2. MANAGER_TEMPLATE có ALLOW cho /api/leads/export GET
    3. Không có entry `/api/leads/export/csv|excel` orphan trong template
    """
    route_paths = _collect_route_paths()

    # 1. Actual route exists in FastAPI app
    assert "/api/leads/export" in route_paths, (
        f"Route /api/leads/export disappeared — update test OR re-add "
        f"endpoint. Existing /api/leads/* routes: "
        f"{sorted(p for p in route_paths if p.startswith('/api/leads'))}"
    )

    entries = _manager_export_entries()

    # 2. Manager template has correct entry
    assert ("/api/leads/export", "GET") in entries, (
        f"MANAGER_TEMPLATE missing /api/leads/export GET. Found: {entries}"
    )

    # 3. No orphan /export/csv or /export/excel entries
    orphans = {
        (obj, act)
        for (obj, act) in entries
        if obj in {"/api/leads/export/csv", "/api/leads/export/excel"}
    }
    assert not orphans, (
        f"Orphan MANAGER_TEMPLATE entries pointing to non-existent paths "
        f"(/api/leads/export/csv|excel are 404; actual route uses "
        f"query param ?format=): {orphans}"
    )


@pytest.mark.asyncio
async def test_no_policy_rows_with_null_eft():
    """W4-1 hotfix anchor: KHÔNG có 'p' (policy) row nào có v3 (eft) NULL.

    Casbin model `p = sub, obj, act, eft` REQUIRE đầy đủ 4 fields. NULL v3
    triggers `RuntimeError("invalid policy size")` trên load_policy() →
    Casbin enforcer chết → all endpoints crash 500.

    History (PR #297 deploy 2026-05-16):
    - Migration qae2e01 INSERT thiếu cột v3 → row 924 NULL eft
    - Manifest qua FE: GET /api/admissions/{id} → 500
    - User fix manual UPDATE row 924 SET v3='allow'
    - qae2e02 hotfix sweep + qae2e01 source patched include v3

    Pattern bug từng xuất hiện trong nhiều migrations cũ
    (bb2j3k4l5m6n, dd5m6n7o8p9q, idor20260216001) — đó là tại sao test
    này là DB-runtime check, không chỉ template check.

    Re-introducing INSERT thiếu v3 sẽ fail test này.
    """
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            text(
                """
                SELECT id, v0, v1, v2, template_id
                FROM casbin_rule
                WHERE ptype = 'p' AND v3 IS NULL
                ORDER BY id
                LIMIT 20
                """
            )
        )
        rows = result.fetchall()
    assert not rows, (
        f"Found {len(rows)} policy rows with NULL eft — will crash Casbin "
        f"load_policy(). Fix migration to include v3='allow' or 'deny'. "
        f"Offending rows: {[(r.id, r.v0, r.v1, r.v2, r.template_id) for r in rows]}"
    )
