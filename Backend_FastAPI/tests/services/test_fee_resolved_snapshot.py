"""Integration test cho snapshot ngành (Fee.resolved_*) + filter parity.

Phủ các vùng rủi ro P1 của workspace "Thu học phí":
- ``resnapshot_fee_academic_info_for_profile`` điền đúng major/degree (legacy +
  multi-NV admitted) · fail-soft NULL khi chưa chốt · skip fee cancelled · refresh
  khi đổi admitted choice (cơ chế các decision hook dựa vào).
- Filter ``major_id`` / ``degree_level``: ``get_filtered_with_count`` (list) và
  ``get_status_counts`` (badge tab) CÙNG điều kiện → CÙNG số (parity P1-1).
- Application fee tạo trước khi chốt (2 NV pending) → NULL; sau khi admit 1 NV →
  re-snapshot có ngành.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app import models
from app.repositories.fee_repository import InvoiceRepository
from app.services.fee_calculation_service import (
    resnapshot_fee_academic_info_for_profile,
)

pytestmark = pytest.mark.integration

_counter = {"n": 0}


def _suffix() -> int:
    _counter["n"] += 1
    return int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000 + _counter["n"]


async def _seed_major_chain(db, unit_id, *, degree="Cao đẳng", tuition=1_000_000):
    """Major + ProgramOffering + OfferingAcademicInfo + Method + AdmissionPath +
    SubjectGroup + PathSubjectGroupConfig. Trả ids để dựng choice / OAC / fee."""
    sfx = _suffix()
    major = models.MajorProgram(
        id=sfx,
        name=f"Ngành {sfx}",
        code=f"MJ{sfx}",
        degree_level=degree,
        unit_id=unit_id,
    )
    db.add(major)
    await db.flush()

    offering = models.ProgramOffering(
        program_id=major.id, offering_type=f"ft_{sfx}", duration_semesters=6,
    )
    db.add(offering)
    await db.flush()

    ai = models.OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=2026,
        annual_admission_quota=50,
        tuition_fee_per_year=tuition,
    )
    db.add(ai)
    await db.flush()

    from tests.fixtures.builders import AdmissionRoundBuilder
    round_id = await AdmissionRoundBuilder.get_or_create_default_round(
        db, academic_year=2026,
    )
    method = models.AdmissionMethod(code=f"MT{sfx}", name=f"PT {sfx}", is_active=True)
    db.add(method)
    await db.flush()

    path = models.AdmissionPath(
        academic_info_id=ai.id,
        admission_method_id=method.id,
        admission_round_id=round_id,
        status="active",
    )
    db.add(path)
    await db.flush()

    sg = models.SubjectGroup(code=f"SG{sfx}"[:20], name=f"Tổ hợp {sfx}")
    db.add(sg)
    await db.flush()
    config = models.PathSubjectGroupConfig(
        admission_path_id=path.id, subject_group_id=sg.id, min_score=Decimal("0"),
    )
    db.add(config)
    await db.flush()

    return {
        "major_id": major.id,
        "degree": degree,
        "academic_info_id": ai.id,
        "path_id": path.id,
        "config_id": config.id,
    }


async def _make_lead_profile(db, unit_id, *, uses_choice_engine, applied_rules=None):
    sfx = _suffix()
    lead = models.Lead(
        full_name=f"HS {sfx}",
        phone=f"098{sfx:07d}"[:10],
        unit_id=unit_id,
        source="walkin",
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        citizen_id=f"8{sfx:09d}"[:12],
        status="submitted",
        applied_rules=applied_rules or {},
        academic_year=2026,
        uses_choice_engine=uses_choice_engine,
    )
    db.add(profile)
    await db.flush()
    return lead, profile


async def _add_choice(db, profile_id, chain, *, order, decision="pending"):
    choice = models.AdmissionProfileChoice(
        admission_profile_id=profile_id,
        admission_path_id=chain["path_id"],
        path_subject_group_config_id=chain["config_id"],
        display_order=order,
        decision=decision,
    )
    db.add(choice)
    await db.flush()
    return choice


async def _add_fee_with_invoice(db, profile_id, *, fee_type="tuition", semester_no=1,
                                amount=Decimal("1000000"), status="invoiced",
                                inv_status="issued"):
    fee = models.Fee(
        admission_profile_id=profile_id,
        fee_type=fee_type,
        academic_year=2026,
        semester_no=semester_no if fee_type == "tuition" else None,
        base_amount=amount,
        total_discount=Decimal("0"),
        final_amount=amount,
        paid_amount=Decimal("0"),
        waived_amount=Decimal("0"),
        status=status,
    )
    db.add(fee)
    await db.flush()
    inv = models.Invoice(
        fee_id=fee.id,
        invoice_number=f"INV-T-{fee.id}",
        installment_no=1,
        amount=amount,
        paid_amount=Decimal("0"),
        penalty_amount=Decimal("0"),
        due_date=date(2026, 9, 1),
        status=inv_status,
    )
    db.add(inv)
    await db.flush()
    return fee, inv


# ── Snapshot helper ─────────────────────────────────────────────────────────

class TestResnapshotHelper:

    async def test_legacy_profile_resolves_major(self, db, seed_lead_dependencies):
        unit = seed_lead_dependencies["unit_id"]
        chain = await _seed_major_chain(db, unit)
        _, profile = await _make_lead_profile(
            db, unit, uses_choice_engine=False,
            applied_rules={"academic_info_id": chain["academic_info_id"]},
        )
        fee, _ = await _add_fee_with_invoice(db, profile.id)

        n = await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(fee)
        assert n == 1
        assert fee.resolved_major_id == chain["major_id"]
        assert fee.resolved_degree_level == chain["degree"]
        assert fee.resolved_academic_info_id == chain["academic_info_id"]

    async def test_failsoft_null_when_two_pending_choices(self, db, seed_lead_dependencies):
        unit = seed_lead_dependencies["unit_id"]
        c1 = await _seed_major_chain(db, unit)
        c2 = await _seed_major_chain(db, unit, degree="Trung cấp")
        _, profile = await _make_lead_profile(db, unit, uses_choice_engine=True)
        await _add_choice(db, profile.id, c1, order=1)
        await _add_choice(db, profile.id, c2, order=2)  # 2 pending → undetermined
        fee, _ = await _add_fee_with_invoice(db, profile.id)

        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(fee)
        assert fee.resolved_major_id is None
        assert fee.resolved_degree_level is None

    async def test_multinv_admitted_uses_admitted_choice(self, db, seed_lead_dependencies):
        """P1-2: admitted choice KHÁC NV gốc → snapshot = ngành ADMITTED."""
        unit = seed_lead_dependencies["unit_id"]
        nv1 = await _seed_major_chain(db, unit, degree="Cao đẳng")
        nv2 = await _seed_major_chain(db, unit, degree="Trung cấp")
        _, profile = await _make_lead_profile(db, unit, uses_choice_engine=True)
        await _add_choice(db, profile.id, nv1, order=1, decision="rejected")
        await _add_choice(db, profile.id, nv2, order=2, decision="admitted")
        fee, _ = await _add_fee_with_invoice(db, profile.id)

        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(fee)
        # Đúng NV2 (admitted), KHÔNG phải NV1 gốc.
        assert fee.resolved_major_id == nv2["major_id"]
        assert fee.resolved_degree_level == "Trung cấp"
        assert fee.resolved_major_id != nv1["major_id"]

    async def test_refreshes_after_decision_change(self, db, seed_lead_dependencies):
        """Cơ chế decision-hook: đổi admitted → re-run helper cập nhật snapshot."""
        unit = seed_lead_dependencies["unit_id"]
        nv1 = await _seed_major_chain(db, unit)
        nv2 = await _seed_major_chain(db, unit, degree="Trung cấp")
        _, profile = await _make_lead_profile(db, unit, uses_choice_engine=True)
        ch1 = await _add_choice(db, profile.id, nv1, order=1, decision="admitted")
        ch2 = await _add_choice(db, profile.id, nv2, order=2, decision="rejected")
        fee, _ = await _add_fee_with_invoice(db, profile.id)

        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(fee)
        assert fee.resolved_major_id == nv1["major_id"]

        # Đổi admitted sang NV2 (như waitlist promote / cascade) → re-snapshot.
        ch1.decision = "rejected"
        ch2.decision = "admitted"
        await db.flush()
        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(fee)
        assert fee.resolved_major_id == nv2["major_id"]

    async def test_skips_cancelled_fee(self, db, seed_lead_dependencies):
        unit = seed_lead_dependencies["unit_id"]
        chain = await _seed_major_chain(db, unit)
        _, profile = await _make_lead_profile(
            db, unit, uses_choice_engine=False,
            applied_rules={"academic_info_id": chain["academic_info_id"]},
        )
        active_fee, _ = await _add_fee_with_invoice(db, profile.id, semester_no=1)
        cancelled_fee, _ = await _add_fee_with_invoice(
            db, profile.id, semester_no=2, status="cancelled", inv_status="cancelled",
        )

        n = await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(active_fee)
        await db.refresh(cancelled_fee)
        assert n == 1  # chỉ fee active
        assert active_fee.resolved_major_id == chain["major_id"]
        assert cancelled_fee.resolved_major_id is None  # KHÔNG relabel fee huỷ

    async def test_application_fee_null_predecision_then_resnapshot(self, db, seed_lead_dependencies):
        """P1: app fee tạo khi 2 NV pending → NULL; admit 1 NV → re-snapshot có ngành."""
        unit = seed_lead_dependencies["unit_id"]
        nv1 = await _seed_major_chain(db, unit)
        nv2 = await _seed_major_chain(db, unit, degree="Trung cấp")
        _, profile = await _make_lead_profile(db, unit, uses_choice_engine=True)
        ch1 = await _add_choice(db, profile.id, nv1, order=1)
        await _add_choice(db, profile.id, nv2, order=2)
        app_fee, _ = await _add_fee_with_invoice(
            db, profile.id, fee_type="application", status="paid", inv_status="paid",
        )

        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(app_fee)
        assert app_fee.resolved_major_id is None  # chưa chốt

        ch1.decision = "admitted"
        await db.flush()
        await resnapshot_fee_academic_info_for_profile(db, profile.id)
        await db.refresh(app_fee)
        assert app_fee.resolved_major_id == nv1["major_id"]  # đã chốt


# ── Filter parity (list == status-counts) ───────────────────────────────────

class TestFilterParity:

    async def test_major_filter_parity(self, db, seed_lead_dependencies):
        unit = seed_lead_dependencies["unit_id"]
        chain = await _seed_major_chain(db, unit)
        other = await _seed_major_chain(db, unit, degree="Trung cấp")
        # 2 hồ sơ ngành `chain`, 1 hồ sơ ngành `other`.
        for _ in range(2):
            _, p = await _make_lead_profile(
                db, unit, uses_choice_engine=False,
                applied_rules={"academic_info_id": chain["academic_info_id"]},
            )
            await _add_fee_with_invoice(db, p.id)
            await resnapshot_fee_academic_info_for_profile(db, p.id)
        _, p2 = await _make_lead_profile(
            db, unit, uses_choice_engine=False,
            applied_rules={"academic_info_id": other["academic_info_id"]},
        )
        await _add_fee_with_invoice(db, p2.id)
        await resnapshot_fee_academic_info_for_profile(db, p2.id)
        await db.flush()

        repo = InvoiceRepository(db)
        invs, total = await repo.get_filtered_with_count(major_id=chain["major_id"], limit=100)
        counts = await repo.get_status_counts(major_id=chain["major_id"])
        # PARITY: list total == status-counts total, đều = 2.
        assert total == 2
        assert counts["total"] == 2
        assert total == counts["total"]
        assert all(i.fee.resolved_major_id == chain["major_id"] for i in invs)

        # Ngành khác → 1 (parity giữ).
        _, t_other = await repo.get_filtered_with_count(major_id=other["major_id"], limit=100)
        c_other = await repo.get_status_counts(major_id=other["major_id"])
        assert t_other == 1 == c_other["total"]

    async def test_degree_filter_parity(self, db, seed_lead_dependencies):
        unit = seed_lead_dependencies["unit_id"]
        cd = await _seed_major_chain(db, unit, degree="Cao đẳng")
        tc = await _seed_major_chain(db, unit, degree="Trung cấp")
        for chain in (cd, cd, tc):
            _, p = await _make_lead_profile(
                db, unit, uses_choice_engine=False,
                applied_rules={"academic_info_id": chain["academic_info_id"]},
            )
            await _add_fee_with_invoice(db, p.id)
            await resnapshot_fee_academic_info_for_profile(db, p.id)
        await db.flush()

        repo = InvoiceRepository(db)
        _, total = await repo.get_filtered_with_count(degree_level="Cao đẳng", limit=100)
        counts = await repo.get_status_counts(degree_level="Cao đẳng")
        assert total == 2 == counts["total"]
