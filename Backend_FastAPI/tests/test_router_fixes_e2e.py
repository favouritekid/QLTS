"""
End-to-end tests for 4 router fixes in admin/users.py.

Tests:
1. admin_set_user_password   — commit + callback
2. bulk_user_action          — unpack tuple + callback
3. import_leads_from_file    — commit + callback
4. update_existing_user      — notification import + unpack + commit
"""
import io
from datetime import datetime, timezone
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
    """Bug #4: notification must be created (no NameError, proper unpack + commit).

    Rule + ACTION, not rule + ``channels``
    --------------------------------------
    The legacy ``notification_rule.channels`` column was DROPPED in Wave 4b
    (migration ``2297e303be04``); the model says so at
    ``app/models/notification.py:110-112``, and the loader now builds its
    delivery plan purely from ``NotificationAction`` rows
    (``app/services/notification_rule_loader.py:712-729``). A rule with zero
    actions yields ``action_configs = []`` → no resolved recipients → the
    dispatcher takes its domain-event-only branch and writes NO inbox row
    (``app/services/notification_dispatcher.py:901-951``). Only browser actions
    produce ``Notification`` rows (``…dispatcher.py:1057, 1105-1114``), so a
    single ``channel="browser"`` action is the minimum viable seed.

    Assertions key on ``data.event`` / ``data.dedupe_key`` / ``user_id``, not on
    the title: a title match would also accept a row written by some other rule
    that happened to reuse the wording.
    """
    target_id = regular_user_in_db["id"]
    started_at = datetime.now(timezone.utc)
    # Router-side dedupe key + the action-scoped suffix the dispatcher appends:
    # app/routers/admin/users.py:1196 and
    # app/services/notification_dispatcher.py:1039.
    expected_dedupe_key = f"user_profile_updated:{target_id}:step1"

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.NotificationRule).where(
                models.NotificationRule.event == "user_profile_updated"
            )
        )
        rule = result.scalars().first()
        if rule is None:
            rule = models.NotificationRule(
                event="user_profile_updated",
                title_template="Your profile has been updated",
                message_template=(
                    "An administrator updated your profile. "
                    "Changed fields: ${updated_fields}."
                ),
                recipient_config={"resolver_type": "specific_users", "params": {}},
                enabled=True,
            )
            db.add(rule)
            await db.flush()

        # Wave 4b: the rule needs at least one action or nothing is delivered.
        action_exists = (await db.execute(
            select(models.NotificationAction).where(
                models.NotificationAction.rule_id == rule.id,
                models.NotificationAction.channel == "browser",
            )
        )).scalars().first()
        if action_exists is None:
            db.add(
                models.NotificationAction(
                    rule_id=rule.id,
                    step=1,
                    channel="browser",
                    content_mode="inherit_default",
                )
            )
        await db.commit()

        from app.services.notification_rule_loader import invalidate_rule_cache
        await invalidate_rule_cache("user_profile_updated")

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
                models.Notification.created_at >= started_at,
            ).order_by(models.Notification.created_at.desc())
        )
        recent = result.scalars().all()
        # Identify by EVENT, not by title — the title is just rendered text.
        matching = [
            n for n in recent
            if (n.data or {}).get("event") == "user_profile_updated"
        ]
        assert matching, (
            "No user_profile_updated notification persisted — NameError, missing "
            "commit, or the rule has no browser NotificationAction. Recent rows: "
            f"{[(n.user_id, (n.data or {}).get('event'), n.title) for n in recent]}"
        )
        # Exactly one recipient overall: this event targets ONE user via
        # SpecificUsersResolver reading payload['user_id'].
        recipients = [n.user_id for n in matching]
        assert recipients == [target_id], (
            "Per-user profile update must reach exactly the updated user; "
            f"got recipients={recipients}, expected [{target_id}]"
        )
        notif = matching[0]
        assert (notif.data or {}).get("dedupe_key") == expected_dedupe_key, (
            "Notification is not the one this dispatch produced: "
            f"dedupe_key={(notif.data or {}).get('dedupe_key')!r}, "
            f"expected {expected_dedupe_key!r}"
        )
        assert (notif.data or {}).get("user_id") == target_id
        assert notif.title == "Your profile has been updated"
        assert "full_name" in notif.message, \
            f"Notification message doesn't mention changed field: {notif.message}"
