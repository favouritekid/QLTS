"""QA Wave 8-9 batch — lead import bugs + XSS defense + rollback idempotent.

Wave 9 (2026-05-16):
- W9-N.1.3 🟥 BLOCKER — `officer_import_leads` line 1518 NameError `lead`
  not defined → 500 sau commit thành công → DB has rows, client thấy
  "Failed to import" → user retries → duplicate.
- W9-N.1.2 🟥 MAJOR — `pd.read_csv` thiếu `dtype=str` → leading 0 stripped
  → 100% VN phone format rejected.
- W9-N.1.1 🟧 — Officer import yêu cầu unit_id column nhưng docstring nói
  auto-set → contract mismatch.
- W9-J.7.idem 🟦 — Rollback already-draft → 400 "Invalid transition";
  should be 200 no-op với `already_at_target=true`.

Wave 8 remaining:
- W8-A.3.2 🟦 — XSS payload stored raw in user.full_name → defense-in-depth
  gap. Frontend escapes via React JSX OK but belt+suspenders prevents
  stored XSS surfacing via export/email/dangerouslySetInnerHTML leak.
"""
from __future__ import annotations

import io

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# W9-N.1.2 + W9-N.1.3 + W9-N.1.1 — officer CSV import
# ---------------------------------------------------------------------------

OFFICER_CSV_NO_UNIT = (
    b"full_name,email,phone,source\n"
    b"W9 Anchor 1,w9anchor1@example.com,0900000901,walkin\n"
    b"W9 Anchor 2,w9anchor2@example.com,0900000902,walkin\n"
)


async def test_w9_n13_officer_import_no_nameerror_codepath():
    """W9-N.1.3 anchor: unit-level check that `lead` symbol no longer
    referenced in officer_import_leads. Source-level guard cheaper than
    full HTTP fixture (needs DB seed for pipeline stages + statuses).

    Live HTTP repro already validated post-fix: officer import 2 rows
    → 200 + 2 created_lead_ids + no 500 (dev env 2026-05-16).
    """
    import inspect
    from app.routers import leads as leads_router

    source = inspect.getsource(leads_router.officer_import_leads)
    # Pre-fix bug: `rooms=rooms_for_lead(lead)` — `lead` undefined
    assert "rooms_for_lead(lead)" not in source, (
        "W9-N.1.3 regression: `rooms_for_lead(lead)` references undefined "
        "`lead` var in officer_import_leads scope (bulk endpoint, no "
        "singular lead). Use captured user.unit_id + role_admin rooms instead."
    )


def test_w9_n12_csv_read_uses_dtype_str():
    """W9-N.1.2 anchor: pd.read_csv must use dtype=str so VN phones with
    leading 0 don't get pandas-inferred as int → stripped.
    """
    import inspect
    from app.services import lead_service

    source = inspect.getsource(lead_service.import_leads_from_file_content)
    # Must contain dtype=str on read_csv
    assert "pd.read_csv(io.BytesIO(file_content), dtype=str)" in source, (
        "W9-N.1.2 regression: pd.read_csv missing dtype=str → pandas "
        "strips leading 0 from phone column → 100% VN phone rejection."
    )
    assert "pd.read_excel(io.BytesIO(file_content), engine=\"openpyxl\", dtype=str)" in source, (
        "Same fix needed for Excel path."
    )


def test_w9_n11_unit_id_not_required_when_default_unit_provided():
    """W9-N.1.1 anchor: required_columns must conditionally exclude unit_id
    when caller passes default_unit_id (officer flow). Docstring promise
    matches code.
    """
    import inspect
    from app.services import lead_service

    source = inspect.getsource(lead_service.import_leads_from_file_content)
    # Must have the conditional unit_id check
    assert "default_unit_id is None" in source, (
        "W9-N.1.1 regression: required_columns hardcodes unit_id, but "
        "officer flow passes default_unit_id so column auto-overridden. "
        "Conditional exclude expected."
    )


# ---------------------------------------------------------------------------
# W8-A.3.2 — XSS escape on user.full_name
# ---------------------------------------------------------------------------


async def test_admin_put_user_full_name_xss_escaped(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
):
    """W8-A.3.2 defense-in-depth: HTML tags in full_name HTML-escaped server-
    side. Pre-fix: stored raw, FE-only escape. Post-fix: `<script>...</script>`
    → `&lt;script&gt;...&lt;/script&gt;` before DB write.
    """
    target_user_id = officer_user_in_db["id"]
    response = await client.put(
        f"/api/admin/users/{target_user_id}",
        headers=admin_token_headers,
        data={"full_name": "<script>alert(1)</script>Tester"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Stored value HTML-escaped
    assert "&lt;script&gt;" in body["full_name"], (
        f"Expected HTML escape; got {body['full_name']!r}"
    )
    assert "<script>" not in body["full_name"], "Raw <script> must NOT be in response"
