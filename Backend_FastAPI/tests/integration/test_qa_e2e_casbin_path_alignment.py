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

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    MANAGER_TEMPLATE,
)
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


def test_no_refunds_policy_entries_in_accountant_template():
    """W2-2 anchor: /api/refunds/* entries không tồn tại trong
    ACCOUNTANT_TEMPLATE seed list.

    Refunds module deferred (no router). Re-introducing entry → ghost
    permission grant cho action không thể thực hiện → confusion + audit
    trail noise. Promote khi router ships per memory `finance-event-
    decisions`.
    """
    objects = _accountant_objects()
    refunds_dead = {o for o in objects if o.startswith("/api/refunds")}
    assert not refunds_dead, (
        f"ACCOUNTANT_TEMPLATE has /api/refunds/* dead policies — refunds "
        f"module deferred (no router). Drop entries: {sorted(refunds_dead)}"
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
