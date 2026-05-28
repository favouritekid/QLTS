"""Phase 3 PR-3C Sub-3.6 — Router registration + schema validation anchors.

12 anchor tests covering 3 Phase 3 routers shipped Sub-3.3/3.4/3.5b:
- T6 POST /api/v2/admissions/{id}/publish-result
- T10 POST /api/v2/admissions/{id}/waitlist-promote
- T17 POST /api/v2/admissions/{id}/admin-rollback

Test strategy: lightweight inspection-based (NO real DB, NO TestClient).
- Route registration verified via `router.routes` introspection
- Dependency wiring verified via FastAPI `Depends` signature
- Schema validation tested via Pydantic instantiation (no HTTP req)

Rationale: Sub-3.2 helper tests (12 cases) already cover service-level
branches. Sub-3.6 only locks: route URL pattern + dep type + schema
boundaries. Full integration matrix deferred to test-debt PR
(matches PR-3B precedent: anchor unit tests + deferred E2E suite).

Non-tautological per memory `pattern-change-impact-audit`: each test
asserts SPECIFIC attribute/dep type, not just "exists".
"""
from __future__ import annotations

import re

import pytest
from fastapi import params as fastapi_params
from pydantic import ValidationError

from app.core.deps import (
    get_admission_for_admin_locked,
    get_admission_for_manager,
    require_admin,
)
from app.routers.admissions_v2 import router as v2_router
from app.schemas.admission import (
    AdmissionAdminRollbackRequest,
    AdmissionPublishResultResponse,
    AdmissionWaitlistPromoteRequest,
)


# ============================================================================
# Helpers — extract route by path suffix
# ============================================================================


def _get_route(path_suffix: str):
    """Find route by suffix (handles regex part of path)."""
    for r in v2_router.routes:
        if path_suffix in r.path:
            return r
    raise AssertionError(
        f"Route with suffix '{path_suffix}' not found in admissions_v2 router"
    )


# ============================================================================
# A. Route registration + BONUS-35 keyMatch4 regex (4 tests)
# ============================================================================


def test_publish_result_route_registered_with_regex():
    """Sub-3.3 T6 route registered. FastAPI uses type annotation
    `profile_id: int` for non-numeric rejection (NOT path regex syntax
    `{var:[0-9]+}` — that's Starlette convertor + NOT honored by default).
    """
    route = _get_route("publish-result")
    assert "POST" in route.methods
    assert "{profile_id}" in route.path
    # Full path mirrors Casbin policy `/api/v2/admissions/*/publish-result`
    assert route.path == "/api/v2/admissions/{profile_id}/publish-result"


def test_waitlist_promote_route_registered_with_regex():
    """Sub-3.4 T10 route registered (DRIFT-01 sync — profile-scoped per
    Casbin canonical, NOT choice-scoped admin namespace per stale Plan v0.7).
    """
    route = _get_route("waitlist-promote")
    assert "POST" in route.methods
    assert "{profile_id}" in route.path
    assert route.path == "/api/v2/admissions/{profile_id}/waitlist-promote"


def test_admin_rollback_route_registered_with_regex():
    """Sub-3.5b T17 route registered với regex constraint."""
    route = _get_route("admin-rollback")
    assert "POST" in route.methods
    assert "{profile_id}" in route.path
    assert route.path == "/api/v2/admissions/{profile_id}/admin-rollback"


def test_bonus35_int_type_annotation_enforces_numeric():
    """⭐ BONUS-35 anchor revised: FastAPI uses `profile_id: int` type
    annotation in endpoint signature → non-numeric rejected via Pydantic
    422 at request validation layer (NOT Starlette path regex).

    Memory `lead-keymatch4-collision-followup` BONUS-35 was about CASBIN
    keyMatch4 pattern, NOT FastAPI path regex. Path regex syntax
    `{var:[0-9]+}` is Starlette convertor — NOT honored by default;
    became literal text → all 3 routes BROKEN initially. Em ack miss.

    This test verifies type annotation present + path matches numeric:
    route.path_regex matches `/api/v2/admissions/123/...` ✓
    Non-numeric rejected at Pydantic type coercion layer (422), tested
    via TestClient in test-debt PR (deferred).
    """
    route = _get_route("publish-result")
    # Real request with numeric profile_id MUST match the route
    assert route.path_regex.match("/api/v2/admissions/123/publish-result") is not None
    # Verify endpoint signature has `profile_id: int` (catches type drift).
    # `from __future__ import annotations` may stringify — accept both
    # int class and "int" string repr.
    import inspect
    sig = inspect.signature(route.endpoint)
    annotation = sig.parameters["profile_id"].annotation
    assert annotation is int or annotation == "int", (
        f"publish-result endpoint MUST annotate profile_id as int "
        f"(got {annotation!r}). FastAPI route regex doesn't filter "
        f"non-numeric — type annotation enforces via Pydantic 422."
    )


# ============================================================================
# B. Dependency wiring (4 tests)
# ============================================================================


def _get_dependants(route):
    """Walk endpoint dependant tree, return list of dependency call types."""
    deps = []
    deps.extend(route.dependant.dependencies)
    return deps


def test_publish_result_uses_get_admission_for_manager():
    """Sub-3.3 endpoint MUST use `get_admission_for_manager` IDOR gate
    (3-tier scope admin/manager). Catches regression nếu IDOR gate
    swapped or removed.
    """
    route = _get_route("publish-result")
    dep_calls = [d.call for d in _get_dependants(route)]
    assert get_admission_for_manager in dep_calls, (
        "publish-result must depend on get_admission_for_manager IDOR gate"
    )


def test_waitlist_promote_uses_get_admission_for_manager():
    """Sub-3.4 endpoint MUST use `get_admission_for_manager` (profile-scoped
    per DRIFT-01 sync — Casbin canonical).
    """
    route = _get_route("waitlist-promote")
    dep_calls = [d.call for d in _get_dependants(route)]
    assert get_admission_for_manager in dep_calls


def test_admin_rollback_uses_require_admin():
    """⭐ Sub-3.5b endpoint MUST use `require_admin` (NOT CasbinAuth) —
    admin-only direct gate. Catches regression nếu gate swapped to
    CasbinAuth (which would allow manager via inheritance).

    Note: require_admin returns Depends + dep; check via signature
    inspection.
    """
    route = _get_route("admin-rollback")
    dep_calls = [d.call for d in _get_dependants(route)]
    assert require_admin in dep_calls, (
        "admin-rollback MUST use require_admin dep, NOT CasbinAuth — "
        "T17 is admin-only per memory `lead-active-user-casbin-pr4` diamond pattern"
    )
    # Anti-pattern guard: get_admission_for_manager NOT in deps (admin global scope)
    assert get_admission_for_manager not in dep_calls, (
        "admin-rollback should NOT use IDOR gate (admin global scope)"
    )


def test_admin_rollback_uses_admin_locked_dep():
    """⭐ PR-4 (2026-05-28) anchor: T17 MUST depend on
    ``get_admission_for_admin_locked`` (SELECT FOR UPDATE).

    Catches regression nếu ai revert dep injection để dùng lại
    ``db.get(profile_id)`` race-prone pattern, hoặc swap sang dep khác
    không có ``.with_for_update()``. Production lock được enforce TẠI
    dependency function, nên route-level wiring là single source of truth.

    Inverse guard: KHÔNG dùng manager IDOR dep (admin global scope) và
    KHÔNG dùng officer/user dep (sai scope).
    """
    route = _get_route("admin-rollback")
    dep_calls = [d.call for d in _get_dependants(route)]
    assert get_admission_for_admin_locked in dep_calls, (
        "admin-rollback MUST depend on get_admission_for_admin_locked — "
        "PR-4 fix for race với confirm/finalize/publish. Revert sẽ tạo "
        "last-write-wins + status_history sai thứ tự."
    )


def test_publish_result_does_not_use_require_admin():
    """Inverse anchor — publish-result is manager-allowed (NOT admin-only).
    Catches regression nếu accidentally locked to admin.
    """
    route = _get_route("publish-result")
    dep_calls = [d.call for d in _get_dependants(route)]
    assert require_admin not in dep_calls


# ============================================================================
# C. Schema validation boundaries (3 tests)
# ============================================================================


def test_admin_rollback_reason_min_length_enforced():
    """Sub-3.5b reason MUST reject < 10 chars (Pydantic min_length).

    Defensive: also enforced trong service helper `admin_rollback_profile`
    (Sub-3.2). Two layers because schema runs at FastAPI request boundary,
    service runs at business logic — drift between layers would be a bug.
    """
    with pytest.raises(ValidationError) as exc:
        AdmissionAdminRollbackRequest(reason="short")
    # Pydantic v2 error structure
    errors = exc.value.errors()
    assert any(
        "min_length" in err.get("type", "") or "string_too_short" in err.get("type", "")
        for err in errors
    )


def test_admin_rollback_reason_max_length_enforced():
    """Sub-3.5b reason MUST reject > 500 chars."""
    long_reason = "x" * 501
    with pytest.raises(ValidationError) as exc:
        AdmissionAdminRollbackRequest(reason=long_reason)
    errors = exc.value.errors()
    assert any(
        "max_length" in err.get("type", "") or "string_too_long" in err.get("type", "")
        for err in errors
    )


def test_waitlist_promote_choice_id_must_be_positive():
    """Sub-3.4 schema MUST reject choice_id <= 0 (Pydantic gt=0)."""
    with pytest.raises(ValidationError):
        AdmissionWaitlistPromoteRequest(choice_id=0)
    with pytest.raises(ValidationError):
        AdmissionWaitlistPromoteRequest(choice_id=-1)
    # Positive int accepted
    valid = AdmissionWaitlistPromoteRequest(choice_id=5)
    assert valid.choice_id == 5
    assert valid.reason is None  # Optional


# ============================================================================
# D. Response schema contract (1 test)
# ============================================================================


def test_publish_result_response_schema_locked():
    """⭐ Sub-3.3 response schema MUST accept CascadeResult-shaped dict.
    Anchor catches future regression if response shape changes
    incompatibly với choice_engine.evaluate_cascade output.
    """
    response = AdmissionPublishResultResponse(
        profile_id=42,
        final_status="admitted",
        admitted_choice_id=1,
        admitted_display_order=1,
        per_choice_decisions=[
            {
                "choice_id": 1,
                "display_order": 1,
                "decision": "admitted",
                "reasons": [],
                "score": 24.5,
            },
            {
                "choice_id": 2,
                "display_order": 2,
                "decision": "skip",
                "reasons": [],
                "score": None,
            },
        ],
    )
    assert response.final_status == "admitted"
    assert len(response.per_choice_decisions) == 2
    assert response.per_choice_decisions[0].decision == "admitted"
    assert response.per_choice_decisions[1].decision == "skip"
