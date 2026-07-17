"""Integration tests (PR-2 Nhóm 1, slice 3) — B2b + B4 + B4b.

Khoá 3 hành vi liên quan "cuộc tư vấn mới nhất":

- B2b (`restore_lead`): khôi phục lead soft-deleted revert pipeline qua
  `_resolve_revert_target` (đối xứng delete B1 / restore B2). Cuộc universal
  mới nhất KHÔNG còn NULL-hoá stage của lead; chuỗi rỗng → initial status.
- B4 (`add_consultation`): CHỈ cuộc mới nhất (theo consultation_date, tie-break
  id) mới ghi đè lead.status/pipeline. Cuộc BACKDATE chỉ được ghi vào lịch sử —
  bỏ validate transition, không mutate lead, trả `status_updated=False`.
- B4b (`AdmissionRepository.get_latest_consultation_for_lead`): tie-break
  `id.desc()` để "latest" đồng nhất với `LeadRepository.get_latest_consultation`
  khi 2 cuộc trùng consultation_date.

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 1 (B2b, B4, B4b).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.repositories import AdmissionRepository, LeadRepository
from app.services import lead_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def slice3_statuses(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """PIPE_A/PIPE_B: human pipeline (updates_pipeline=True, có stage).
    UNIV: universal (updates_pipeline=False, stage_id=NULL)."""
    stages = [
        models.PipelineStage(id="S3_STG_A", name="S3 Stage A", order=31),
        models.PipelineStage(id="S3_STG_B", name="S3 Stage B", order=32),
    ]
    for s in stages:
        db.add(s)
    await db.flush()

    statuses = {
        "PIPE_A": models.ConsultationStatus(
            id="S3_PIPE_A", name="S3 Pipe A", color_code="#111111",
            stage_id="S3_STG_A", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "PIPE_B": models.ConsultationStatus(
            id="S3_PIPE_B", name="S3 Pipe B", color_code="#222222",
            stage_id="S3_STG_B", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "UNIV": models.ConsultationStatus(
            id="S3_UNIV", name="S3 Universal", color_code="#333333",
            stage_id=None, is_final=False, updates_pipeline=False,
            is_universal=True, phase="consultation",
        ),
        # legacy_status="new" + is_final=False → StatusHelper.get_initial_status
        # nhận diện đây là initial (prod = sts00; test DB conftest không seed
        # thuộc tính này nên phải tự seed cho nhánh 'rỗng' của helper).
        "INIT": models.ConsultationStatus(
            id="S3_INIT", name="S3 Initial", color_code="#444444",
            stage_id="S3_STG_A", is_final=False, updates_pipeline=True,
            phase="consultation", legacy_status="new",
        ),
    }
    for st in statuses.values():
        db.add(st)
    await db.flush()
    return statuses


async def _make_lead(db, seeded_dependencies, officer_id, cur_status, cur_stage):
    """Lead với status/stage HIỆN TẠI cho trước (mô phỏng add_consultation đã set)."""
    lead = models.Lead(
        full_name="Slice3 Lead",
        phone="0900888777",
        email="slice3_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_id,
        consultation_status_id=cur_status,
        pipeline_stage_id=cur_stage,
        consultation_count=0,
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, status_id, minutes):
    """Consultation trực tiếp, date = _BASE + minutes (điều khiển order/tie)."""
    c = models.Consultation(
        lead_id=lead_id,
        officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method="phone",
        consultation_status_id=status_id,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


# ===========================================================================
# B2b — restore_lead revert dùng _resolve_revert_target (admin-only)
# ===========================================================================


async def test_restore_lead_universal_latest_does_not_null_stage(
    db, seeded_dependencies, slice3_statuses, admin_user, officer_user
):
    """Cuộc universal là mới nhất khi lead bị xoá. Bug cũ (H5): restore gán
    lead.pipeline_stage_id = UNIV.stage_id = NULL. B2b: helper dò về PIPE_A →
    stage KHÔNG bị NULL-hoá, lead trở về PIPE_A."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "S3_PIPE_A", "S3_STG_A")
    await _add_consult(db, lead.id, off, "S3_PIPE_A", 10)
    await _add_consult(db, lead.id, off, "S3_UNIV", 30)  # latest, universal

    await lead_service.delete_lead(db, lead.id, deleted_by=admin_user)
    await db.commit()

    await lead_service.restore_lead(db, lead.id, restored_by=admin_user)
    await db.commit()

    lead = await db.get(models.Lead, lead.id)
    assert lead.deleted_at is None
    assert lead.consultation_status_id == "S3_PIPE_A"
    assert lead.pipeline_stage_id == "S3_STG_A"
    assert lead.pipeline_stage_id is not None


async def test_restore_lead_pipeline_latest_reverts_to_it(
    db, seeded_dependencies, slice3_statuses, admin_user, officer_user
):
    """Cuộc pipeline PIPE_B là mới nhất khi xoá → restore đưa lead về PIPE_B."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "S3_PIPE_A", "S3_STG_A")
    await _add_consult(db, lead.id, off, "S3_PIPE_A", 10)
    await _add_consult(db, lead.id, off, "S3_PIPE_B", 30)  # latest, pipeline

    await lead_service.delete_lead(db, lead.id, deleted_by=admin_user)
    await db.commit()

    await lead_service.restore_lead(db, lead.id, restored_by=admin_user)
    await db.commit()

    lead = await db.get(models.Lead, lead.id)
    assert lead.consultation_status_id == "S3_PIPE_B"
    assert lead.pipeline_stage_id == "S3_STG_B"


async def test_restore_lead_empty_chain_reverts_to_initial(
    db, seeded_dependencies, slice3_statuses, admin_user, officer_user
):
    """Lead không consultation nào → helper nhánh 'rỗng' trả initial status
    (giữ hành vi H5 else cũ, không hardcode 'new')."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "S3_PIPE_A", "S3_STG_A")

    await lead_service.delete_lead(db, lead.id, deleted_by=admin_user)
    await db.commit()

    await lead_service.restore_lead(db, lead.id, restored_by=admin_user)
    await db.commit()

    lead = await db.get(models.Lead, lead.id)
    assert lead.consultation_status_id == "S3_INIT"
    assert lead.pipeline_stage_id == "S3_STG_A"


# ===========================================================================
# B4 — add_consultation: chỉ cuộc mới nhất mới ghi đè lead.status
# ===========================================================================


async def test_backdate_consultation_does_not_overwrite_status(
    db, seeded_dependencies, slice3_statuses, officer_user
):
    """Lead ở PIPE_B với cuộc live mới nhất PIPE_B (+30). Thêm cuộc BACKDATE
    PIPE_A (+10 < +30) → KHÔNG ghi đè lead.status/stage, status_updated=False,
    nhưng record VẪN được tạo. PIPE_A không thuộc PHASE_STATUSES → nếu validate
    transition chạy sẽ raise BadRequest → test cũng chứng minh 'bỏ validate
    transition' cho backdate."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "S3_PIPE_B", "S3_STG_B")
    await _add_consult(db, lead.id, off, "S3_PIPE_B", 30)  # live latest

    data = schemas.ConsultationCreate(
        status_id="S3_PIPE_A",
        consultation_date=_BASE + timedelta(minutes=10),  # backdate
        method="phone",
    )
    consult, status_updated, reason = await lead_service.add_consultation(
        db, lead.id, off, data
    )
    await db.commit()

    lead = await db.get(models.Lead, lead.id)
    assert lead.consultation_status_id == "S3_PIPE_B"  # KHÔNG bị backdate cướp
    assert lead.pipeline_stage_id == "S3_STG_B"
    assert status_updated is False
    # Record backdate vẫn được ghi nhận vào lịch sử.
    assert consult is not None
    assert consult.consultation_status_id == "S3_PIPE_A"


async def test_latest_consultation_overwrites_status(
    db, seeded_dependencies, slice3_statuses, officer_user
):
    """Lead chưa có consultation_status (bỏ phase guard), có cuộc live PIPE_A
    (+10). Thêm cuộc PIPE_B (+20 ≥ +10) → là mới nhất → ghi đè lead sang
    PIPE_B/STG_B, status_updated=True (đường hạnh phúc B4 không phá)."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, None, None)
    await _add_consult(db, lead.id, off, "S3_PIPE_A", 10)

    data = schemas.ConsultationCreate(
        status_id="S3_PIPE_B",
        consultation_date=_BASE + timedelta(minutes=20),  # newer → latest
        method="phone",
    )
    consult, status_updated, reason = await lead_service.add_consultation(
        db, lead.id, off, data
    )
    await db.commit()

    lead = await db.get(models.Lead, lead.id)
    assert lead.consultation_status_id == "S3_PIPE_B"
    assert lead.pipeline_stage_id == "S3_STG_B"
    assert status_updated is True


# ===========================================================================
# B4b — tie-break "latest" đồng nhất giữa 2 repository
# ===========================================================================


async def test_admission_and_lead_latest_agree_on_date_tie(
    db, seeded_dependencies, slice3_statuses, officer_user
):
    """Hai cuộc TRÙNG consultation_date. Trước B4b admission_repo thiếu
    id.desc() → thứ tự do Postgres quyết → có thể lệch lead_repo. Sau B4b: cả
    hai cùng trả cuộc id lớn hơn (c2)."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "S3_PIPE_A", "S3_STG_A")
    c1 = await _add_consult(db, lead.id, off, "S3_PIPE_A", 10)  # id nhỏ hơn
    c2 = await _add_consult(db, lead.id, off, "S3_PIPE_B", 10)  # cùng date, id lớn hơn
    assert c2.id > c1.id

    lead_latest = await LeadRepository(db).get_latest_consultation(lead.id)
    adm_latest = await AdmissionRepository(db).get_latest_consultation_for_lead(
        lead.id
    )
    assert lead_latest.id == c2.id
    assert adm_latest.id == c2.id  # B4b: tie-break id.desc() → khớp lead repo
