# tests/services/test_lead_antifraud.py
"""Antifraud hardening tests — xem Documents/LEAD_ANTIFRAUD_PLAN.md.

Phủ:
- V3: validate ``source`` theo LeadSourceEnum (chống nhập nguồn rác).
- V1/L1: audit completeness — đổi ``referrer_id`` được ghi vào entity_audit_log.
- V1 soft-warn: officer gán CTV / đổi source->referral SAU auto-assign → audit
  action='flagged'; admin/manager hoặc no-op thì KHÔNG flag.
"""
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.services import lead_service


# Patch các side-effect ngoài phạm vi test (scoring cần rules, cache cần Redis).
def _patches():
    return (
        patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=50,
        ),
        patch(
            "app.services.lead_cache_service.update_lead_cache",
            new_callable=AsyncMock,
        ),
    )


async def _audit_rows(db: AsyncSession, lead_id: int, action: str):
    res = await db.execute(
        select(models.EntityAuditLog).where(
            models.EntityAuditLog.entity_type == "Lead",
            models.EntityAuditLog.entity_id == lead_id,
            models.EntityAuditLog.action == action,
        )
    )
    return res.scalars().all()


# ---------------------------------------------------------------------------
# V3 — Source validation (pure schema, no DB)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSourceValidation:
    def test_lead_update_rejects_unknown_source(self):
        with pytest.raises(ValidationError):
            schemas.LeadUpdate(source="bogus_source")

    def test_lead_update_accepts_known_source_and_none(self):
        assert schemas.LeadUpdate(source="referral").source == "referral"
        assert schemas.LeadUpdate().source is None  # không truyền source

    def test_lead_create_allows_freeform_source(self):
        """CỐ Ý không siết create/import (tránh vỡ bulk-import) — chỉ siết edit (#2)."""
        obj = schemas.LeadCreate(full_name="X", phone="0901234567", source="facebook")
        assert obj.source == "facebook"

    def test_lead_create_accepts_known_source(self):
        obj = schemas.LeadCreate(full_name="X", phone="0901234567", source="website")
        assert obj.source == "website"

    def test_response_schema_accepts_legacy_source(self):
        """Đọc lead source legacy ngoài enum KHÔNG được raise (regression #1)."""
        from datetime import datetime

        common = dict(
            id=1, full_name="X", phone="0901234567", source="facebook",
            status="new", lead_score=0,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        assert schemas.Lead(**common).source == "facebook"
        assert schemas.LeadDetail(**common).source == "facebook"


# ---------------------------------------------------------------------------
# V1 / L1 — Audit completeness cho referrer_id
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestReferrerAuditCompleteness:
    async def test_referrer_change_is_audited(
        self, db, seeded_dependencies, officer_user, active_collaborator, seeded_lead
    ):
        """Đổi referrer_id phải xuất hiện trong changes của audit 'updated'."""
        lead_in = schemas.LeadUpdate(referrer_id=active_collaborator.id)
        p_score, p_cache = _patches()
        with p_score, p_cache:
            result, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=officer_user
            )
            await db.commit()
            if cb:
                await cb()

        assert result.referrer_id == active_collaborator.id
        rows = await _audit_rows(db, seeded_lead.id, "updated")
        assert any(r.changes and "referrer_id" in r.changes for r in rows), (
            "referrer_id phải được ghi vào entity_audit_log (bịt điểm mù L1)"
        )


# ---------------------------------------------------------------------------
# V1 — Soft-warn flag
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestSoftWarnReferralAfterAutoassign:
    async def test_officer_assigns_ctv_after_autoassign_is_flagged(
        self, db, seeded_dependencies, officer_user, active_collaborator, seeded_lead
    ):
        """Officer gán CTV trên lead đã auto-assign → audit action='flagged'."""
        lead_in = schemas.LeadUpdate(referrer_id=active_collaborator.id)
        p_score, p_cache = _patches()
        with p_score, p_cache:
            _, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=officer_user
            )
            await db.commit()
            if cb:
                await cb()

        flagged = await _audit_rows(db, seeded_lead.id, "flagged")
        assert len(flagged) == 1
        assert flagged[0].actor_user_id == officer_user.id

    async def test_officer_swaps_referrer_is_flagged(
        self, db, seeded_dependencies, officer_user, active_collaborator, seeded_lead
    ):
        """Officer đổi referrer A→B (CTV khác của mình) — swap phải bị flag (#3)."""
        from datetime import datetime, timezone

        ctv_b = models.Collaborator(
            code="CTV-SWAP-B", full_name="CTV B", phone="0911777888",
            status="active", unit_id=seeded_dependencies["unit_id"],
            managed_by_officer_id=officer_user.id,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(ctv_b)
        # Lead đã có referrer A + source 'referral' từ trước.
        seeded_lead.referrer_id = active_collaborator.id
        seeded_lead.source = "referral"
        await db.flush()

        lead_in = schemas.LeadUpdate(referrer_id=ctv_b.id)
        p_score, p_cache = _patches()
        with p_score, p_cache:
            _, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=officer_user
            )
            await db.commit()
            if cb:
                await cb()

        flagged = await _audit_rows(db, seeded_lead.id, "flagged")
        assert len(flagged) == 1

    async def test_officer_changes_source_to_referral_is_flagged(
        self, db, seeded_dependencies, officer_user, seeded_lead
    ):
        """Officer đổi source sang 'referral' (không referrer) → flagged."""
        lead_in = schemas.LeadUpdate(source="referral")
        p_score, p_cache = _patches()
        with p_score, p_cache:
            _, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=officer_user
            )
            await db.commit()
            if cb:
                await cb()

        flagged = await _audit_rows(db, seeded_lead.id, "flagged")
        assert len(flagged) == 1

    async def test_admin_assigns_ctv_is_not_flagged(
        self, db, seeded_dependencies, admin_user, active_collaborator, seeded_lead
    ):
        """Admin gán CTV → KHÔNG flag (chỉ officer mới bị soft-warn)."""
        lead_in = schemas.LeadUpdate(referrer_id=active_collaborator.id)
        p_score, p_cache = _patches()
        with p_score, p_cache:
            _, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=admin_user
            )
            await db.commit()
            if cb:
                await cb()

        flagged = await _audit_rows(db, seeded_lead.id, "flagged")
        assert len(flagged) == 0

    async def test_officer_noop_update_is_not_flagged(
        self, db, seeded_dependencies, officer_user, seeded_lead
    ):
        """Officer cập nhật field thường (không referrer/source) → KHÔNG flag."""
        lead_in = schemas.LeadUpdate(full_name="Đổi Tên Khách")
        p_score, p_cache = _patches()
        with p_score, p_cache:
            _, cb = await lead_service.update_lead(
                db, seeded_lead.id, lead_in, updated_by=officer_user
            )
            await db.commit()
            if cb:
                await cb()

        flagged = await _audit_rows(db, seeded_lead.id, "flagged")
        assert len(flagged) == 0
