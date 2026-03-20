"""
End-to-end tests for 4 router fixes in admin/users.py.

Tests:
1. admin_set_user_password   — commit + callback
2. bulk_user_action          — unpack tuple + callback
3. import_leads_from_file    — commit + callback
4. update_existing_user      — notification import + unpack + commit
"""
import io
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app import models
from app.security import verify_password


# ---------------------------------------------------------------------------
# Test 1: admin_set_user_password — verify password actually persists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_set_password_persists(
    client: AsyncClient,
    admin_token_headers: dict,
    regular_user_in_db: dict,
):
    """Bug #1: password change must be committed to DB."""
    target_id = regular_user_in_db["id"]
    new_password = "NewSecure@Pass1!"

    resp = await client.post(
        f"/api/admin/users/{target_id}/password",
        json={"new_password": new_password},
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, f"Set password failed: {resp.status_code} {resp.text[:300]}"

    # Verify the password was actually committed to DB
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.User).where(models.User.id == target_id)
        )
        user = result.scalars().first()
        assert user is not None
        assert verify_password(new_password, user.password_hash), \
            "Password NOT committed to DB — transaction rollback bug!"


# ---------------------------------------------------------------------------
# Test 2: bulk_user_action — verify tuple unpack (response is string, not tuple)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_action_response_is_string(
    client: AsyncClient,
    admin_token_headers: dict,
    regular_user_in_db: dict,
):
    """Bug #2: response.detail must be a string, not a raw tuple."""
    target_id = regular_user_in_db["id"]

    resp = await client.post(
        "/api/admin/users/bulk",
        json={
            "action": "change_status",
            "user_ids": [target_id],
            "status": "active",
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, f"Bulk action failed: {resp.status_code} {resp.text[:300]}"

    detail = resp.json().get("detail", "")
    assert isinstance(detail, str), f"detail is not str: {type(detail)}"
    # Before fix, detail was the repr of a tuple: "('Successfully ...', <coroutine ...>)"
    assert not detail.startswith("("), f"detail looks like a raw tuple: {detail[:100]}"


# ---------------------------------------------------------------------------
# Test 3: import_leads_from_file — verify leads actually persist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_leads_persists(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Bug #3: imported leads must be committed to DB, not rolled back."""
    unit_id = seed_lead_dependencies["unit_id"]

    # Ensure an initial status exists with legacy_status="new", is_final=False
    # (StatusHelper.get_initial_status queries by these fields)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.ConsultationStatus).where(
                models.ConsultationStatus.legacy_status == "new",
                models.ConsultationStatus.is_final == False,
            )
        )
        if not result.scalars().first():
            # Patch the existing seeded status to match StatusHelper query
            status_id = seed_lead_dependencies["initial_status_id"]
            result = await db.execute(
                select(models.ConsultationStatus).where(
                    models.ConsultationStatus.id == status_id
                )
            )
            status = result.scalars().first()
            if status:
                status.legacy_status = "new"
                status.is_final = False
                await db.commit()

    unique_suffix = id(object())
    csv_content = (
        "full_name,email,phone,source,unit_id\n"
        f"E2E Import Test,e2e_import_{unique_suffix}@example.com,+84901234567,website,{unit_id}\n"
    )
    csv_bytes = csv_content.encode("utf-8")

    resp = await client.post(
        "/api/admin/users/leads/import",
        files={"file": ("test_leads.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, f"Import failed: {resp.status_code} {resp.text[:300]}"

    body = resp.json()
    created_ids = body.get("created_lead_ids", [])
    assert len(created_ids) > 0, f"No leads created. Body: {body}"

    # Verify leads are in DB (committed, not rolled back)
    async with AsyncSessionLocal() as db:
        for lead_id in created_ids:
            result = await db.execute(
                select(models.Lead).where(models.Lead.id == lead_id)
            )
            lead = result.scalars().first()
            assert lead is not None, \
                f"Lead {lead_id} NOT in DB — transaction was rolled back!"


# ---------------------------------------------------------------------------
# Test 4: update_existing_user notification — no NameError, notification persists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_user_creates_notification(
    client: AsyncClient,
    admin_token_headers: dict,
    regular_user_in_db: dict,
):
    """Bug #4: notification must be created (no NameError, proper unpack + commit)."""
    target_id = regular_user_in_db["id"]

    resp = await client.put(
        f"/api/admin/users/{target_id}",
        data={"full_name": "E2E Notification Test Name"},
        headers=admin_token_headers,
    )
    assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"

    # Verify notification was created and committed
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.Notification).where(
                models.Notification.user_id == target_id,
                models.Notification.type == "admin_update",
            ).order_by(models.Notification.created_at.desc()).limit(1)
        )
        notif = result.scalars().first()
        assert notif is not None, \
            "Notification NOT created — NameError or missing commit!"
        assert "full_name" in notif.message, \
            f"Notification message doesn't mention changed field: {notif.message}"
