"""F10 anchor: 3 admission action routes enforce Casbin BEFORE Pydantic body validation.

QA Wave 1 §E §F10 (2026-05-15) surfaced:
- Officer POST /api/admissions/39/reject empty body → 422 (leak Pydantic schema)
- Same for /request-revision, /drop
Expected: 403 PERMISSION_DENIED without schema disclosure.

Root cause: routes used `Depends(get_current_active_user)` + INLINE role
check inside function body. FastAPI's `solve_dependencies` parses Pydantic
body params BEFORE function body runs, so a permission-less user with
invalid body gets 422 instead of 403. Schema field names leak (`reason`,
`version`, `notes`, `fields`).

Fix (2026-05-16 Batch F): swap `Depends(get_current_active_user)` →
`CasbinAuth` (`Depends(check_permission)`). `check_permission` raises
`PermissionDeniedError` during `solve_dependencies` phase 1, before body
parse. Body never touched for denied users.

Behavior table:
| Role        | Empty body  | Valid body         |
|-------------|-------------|--------------------|
| officer     | 403         | 403                |
| accountant  | 403         | 403                |
| manager     | 422 (schema)| 200/400 (state)    |
| admin       | 422 (schema)| 200/400 (state)    |

Anchors lock the fix: officer gets 403 regardless of body shape; manager
gets 422 only with invalid body (proves Casbin passed).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# All 3 routes share the same dep+body pattern. Parametrize so a future
# regression on any one of them fails distinctly.
F10_ROUTES = [
    "/api/admissions/{profile_id}/reject",
    "/api/admissions/{profile_id}/request-revision",
    "/api/admissions/{profile_id}/drop",
]


@pytest.mark.parametrize("route", F10_ROUTES)
async def test_officer_403_before_body_validation(
    route: str,
    client: AsyncClient,
    officer_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Officer hits route with EMPTY body → 403, not 422.

    Empty body would normally trigger Pydantic 422. Verifying 403 proves
    Casbin runs first (F10 fix). 403 body text contains `PERMISSION_DENIED`
    error code (consistent with other Casbin denies).
    """
    # profile_id=1 chosen arbitrarily; the IDOR/state check happens
    # in service layer AFTER Casbin, so any int works for this anchor.
    url = route.format(profile_id=1)
    response = await client.post(url, headers=officer_token_headers, json={})
    assert response.status_code == 403, (
        f"Officer {route} empty body expected 403 (Casbin deny first); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    assert body.get("error_code") == "PERMISSION_DENIED", (
        f"Expected PERMISSION_DENIED error code; got: {body}"
    )
    # Schema details must NOT leak — no body field names in response
    assert "loc" not in response.text, (
        f"Pydantic validation `loc` field leaked in 403 response: {response.text[:200]}"
    )


@pytest.mark.parametrize("route", F10_ROUTES)
async def test_manager_422_with_invalid_body_proves_casbin_passed(
    route: str,
    client: AsyncClient,
    manager_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Manager hits route with EMPTY body → 422 (NOT 403).

    Manager has Casbin ALLOW on these 3 routes, so:
    - Casbin passes (no 403)
    - Pydantic body validation runs and fails (422 with schema details)

    This is the EXPECTED behavior: schema leak only happens to roles that
    SHOULD be able to see schema. Officer/accountant get 403 first.

    The 422 verifies the route IS still using body validation (didn't get
    accidentally bypassed by the F10 fix).
    """
    url = route.format(profile_id=1)
    response = await client.post(url, headers=manager_token_headers, json={})
    assert response.status_code == 422, (
        f"Manager {route} empty body expected 422 (Casbin allowed, body invalid); "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    assert body.get("error_code") == "VALIDATION_ERROR"
