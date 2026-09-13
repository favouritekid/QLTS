"""B1 (2026-09-13) — override KV hợp lệ phải SỐNG qua freeze, kèm dấu vết duyệt.

Bối cảnh đo được trước bản vá
-----------------------------
``priority_service.resolve_kv_for_profile`` trả ``(None, {"rule_applied":
"manual_override"})`` cho nhánh ``basis == MANUAL`` — engine cố ý không tự
resolve và giao caller giữ ``kv_resolved`` đang có. ``freeze_priority_snapshot``
lại dựng snapshot MỚI từ số 0 ⇒ ``kv_resolved=None`` + mất
``manual_override_by/_at/_reason``. Đường T6
(``admission_choice_engine_service`` freeze rồi ``calculate_priority_bonus``)
nuốt luôn: ``_resolve_area_bonus`` thấy ``kv_resolved`` None thì ``return
_ZERO`` — 0 điểm khu vực, không lỗi, không log.

Bất biến mỗi ca khoá (MỘT ca = MỘT bất biến)
--------------------------------------------
1. ``test_override_hop_le_song_qua_freeze``      — giữ được KV + dấu vết.
2. ``test_override_hop_le_van_cham_diem_khu_vuc``— KV giữ được thì CHẤM ĐIỂM.
3. ``test_put_thuong_khong_bat_duoc_manual_override`` — lối vào PUT bị chặn.
4. ``test_nhan_manual_tren_snapshot_engine_khong_phai_chung_cu`` — nhãn MANUAL
   đè lên snapshot do engine tính KHÔNG được công nhận.
5. ``test_snapshot_day_du_nhung_khong_co_hang_audit_thi_fail_closed`` — dấu vết
   trong snapshot tự nó KHÔNG phải chứng cứ; phải có hàng ``priority_audit_log``.
6. ``test_override_het_hieu_luc_khi_du_lieu_kv_doi`` — đổi đầu vào KV ⇒ hết hiệu lực.
7. ``test_hang_audit_role_officer_khong_duoc_cong_nhan`` — role ngoài
   {admin,manager} (hàng cũ trước Phase E.4 commit 7) ⇒ không công nhận.
8. ``test_hang_audit_khong_co_van_tay_thi_fail_closed`` — hàng audit cũ.
9. ``test_cascade_t6_giu_override_va_cham_diem_khu_vuc`` — ĐƯỜNG THẬT
   ``evaluate_cascade`` (không monkeypatch logic đang nghiệm thu).
10. ``test_publish_result_giu_override_va_cham_diem_khu_vuc`` — ĐƯỜNG THẬT
    ``publish_result`` (đúng entrypoint router gọi, đi qua cả tiền-điều-kiện
    + tự chuyển submitted -> reviewing).
11. ``test_guard_kv_unresolved_khong_bi_noi`` — chứng minh KHÔNG nới guard.
12. ``test_freeze_giu_ut_verified_bucket`` — nhánh anh em cùng lỗi "dựng lại
    snapshot từ số 0".

Chạy: docker compose -p b1t -f docker-compose.b1t.yml run --rm --no-deps backend \
        "python -m pytest tests/api/test_b1_kv_override_preserve.py -q"
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal
from app.models.priority_audit import PriorityAuditLog
from app.models.priority_config import PriorityAreaConfig

# asyncio_mode=auto (pytest.ini) tự nhận async test; KHÔNG đặt pytestmark asyncio
# (ca đồng bộ số 10 sẽ ăn mark thừa và pytest cảnh báo).
pytestmark = pytest.mark.integration


ACADEMIC_YEAR = 2026
KV1_RATE = Decimal("0.75")
KV3_RATE = Decimal("0.00")
OVERRIDE_REASON = "Xac minh ho khau tai xa dac biet kho khan, ho so giay dinh kem."


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_area_rates(session) -> None:
    """KV1 = 0.75đ, KV3 = 0.00đ cho ``ACADEMIC_YEAR``.

    KV3 cố ý 0đ: nó là KV engine tự tính ra cho hồ sơ mẫu, nên "điểm khu vực
    > 0" CHỈ có thể đến từ override KV1 được giữ lại — không thể xanh nhờ
    engine.
    """
    existing = (
        await session.execute(
            select(PriorityAreaConfig.area_code).where(
                PriorityAreaConfig.academic_year == ACADEMIC_YEAR
            )
        )
    ).scalars().all()
    for code, name, pts in (
        ("KV1", "Khu vuc 1", KV1_RATE),
        ("KV3", "Khu vuc 3", KV3_RATE),
    ):
        if code in existing:
            continue
        session.add(
            PriorityAreaConfig(
                academic_year=ACADEMIC_YEAR,
                area_code=code,
                area_name=name,
                bonus_points=pts,
                effective_from=date(2025, 1, 1),
                effective_to=None,
            )
        )
    await session.flush()


async def _seed_profile(
    seed_lead_dependencies: dict,
    *,
    status: str,
    uses_choice_engine: bool = False,
    kv_unresolvable: bool = False,
) -> dict:
    """Hồ sơ mẫu: engine resolve được KV3 qua lịch sử THPT (LICH_SU_THPT)."""
    from tests.fixtures.builders import (
        ensure_submittable_ward,
        seed_submittable_offering_config,
        submittable_profile_fields,
    )

    await ensure_submittable_ward()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            seed = await seed_submittable_offering_config(
                s, unit_id=seed_lead_dependencies["unit_id"],
                academic_year=ACADEMIC_YEAR,
            )
            await _seed_area_rates(s)

            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            lead = models.Lead(
                full_name=f"B1 lead {ts}",
                phone=f"09{ts:08d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            fields = submittable_profile_fields(seed)
            fields["uses_choice_engine"] = uses_choice_engine
            if kv_unresolvable:
                # Cùng trường, nhưng NĂM nằm ngoài khoảng VnSchoolKvAssignment
                # (2020-2024) ⇒ mọi lượt tra KV trượt ⇒ engine trả
                # rule_applied='catalog_gap_school' + requires_manual_override.
                # Đây là tiền đề của cổng override-draft.
                fields["academic_history"] = [{
                    **fields["academic_history"][0],
                    "year_from": 2010,
                    "year_to": 2014,
                }]
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"8{ts:08d}0"[:12],
                status=status,
                academic_year=ACADEMIC_YEAR,
                applied_rules={},
                **fields,
            )
            s.add(profile)
            await s.flush()
            out = {
                "profile_id": profile.id,
                "lead_id": lead.id,
                "seed": seed,
                "version": profile.version,
            }
    return out


@pytest_asyncio.fixture
async def submitted_profile(seed_lead_dependencies: dict) -> dict:
    return await _seed_profile(seed_lead_dependencies, status="submitted")


@pytest_asyncio.fixture
async def draft_profile_kv_unresolvable(seed_lead_dependencies: dict) -> dict:
    return await _seed_profile(
        seed_lead_dependencies, status="draft", kv_unresolvable=True,
    )


@pytest_asyncio.fixture
async def draft_profile(seed_lead_dependencies: dict) -> dict:
    return await _seed_profile(seed_lead_dependencies, status="draft")


# ---------------------------------------------------------------------------
# Thao tác dùng chung — MÃ SẢN PHẨM THẬT, không monkeypatch
# ---------------------------------------------------------------------------


async def _load_profile(session, profile_id: int) -> models.AdmissionProfile:
    return (
        await session.execute(
            select(models.AdmissionProfile).where(
                models.AdmissionProfile.id == profile_id
            )
        )
    ).scalar_one()


async def _read_snapshot_from_db(profile_id: int) -> dict:
    """Đọc THẲNG cột JSONB trong một session MỚI (không đọc lại từ identity map)."""
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(models.AdmissionProfile.priority_resolution_snapshot).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()
    return dict(row or {})


async def _run_freeze(profile_id: int, frozen_at_status: str = "engine_T6") -> dict:
    """Gọi ĐÚNG hàm mà T1 (submit) và T6 (engine) đều gọi."""
    from app.services.priority_service import freeze_priority_snapshot

    async with AsyncSessionLocal() as s:
        profile = await _load_profile(s, profile_id)
        snapshot = await freeze_priority_snapshot(
            profile=profile,
            db=s,
            frozen_at_status=frozen_at_status,
            resolved_by="system",
        )
        await s.commit()
    return dict(snapshot)


async def _area_bonus_for(profile_id: int) -> tuple[Decimal, dict]:
    """``calculate_priority_bonus`` thật, rule bật KV."""
    from app.services.priority_service import calculate_priority_bonus

    async with AsyncSessionLocal() as s:
        profile = await _load_profile(s, profile_id)
        area, _obj, cfg = await calculate_priority_bonus(
            db=s,
            profile=profile,
            rule={"apply_area_bonus": True, "apply_object_bonus": False},
            academic_year=ACADEMIC_YEAR,
        )
    return area, cfg


async def _http_override(
    client, headers: dict, profile_id: int, *, kv: str, version: int,
    reason: str = OVERRIDE_REASON,
):
    return await client.post(
        f"/api/v2/admissions/{profile_id}/override-priority-kv",
        json={"version": version, "kv_resolved": kv, "reason": reason},
        headers=headers,
    )


async def _latest_audit_row(profile_id: int) -> Optional[dict]:
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(PriorityAuditLog)
                .where(
                    PriorityAuditLog.profile_id == profile_id,
                    PriorityAuditLog.action_type == "kv_manual_override",
                )
                .order_by(PriorityAuditLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is None:
            return None
        return {
            "id": row.id,
            "actor_id": row.actor_id,
            "new_value": dict(row.new_value or {}),
            "metadata": dict(row.audit_metadata or {}),
            "created_at": row.created_at,
        }


async def _override_via_endpoint(client, headers, profile_id: int, kv: str) -> dict:
    """Freeze nền (engine ⇒ KV3) rồi override qua ĐÚNG endpoint được phép."""
    before = await _run_freeze(profile_id, frozen_at_status="submitted_T1")
    assert before["kv_resolved"] == "KV3", before
    assert before["rule_applied"] in (
        "longest_duration", "tiebreak_graduation_school",
    ), before

    async with AsyncSessionLocal() as s:
        version = (
            await s.execute(
                select(models.AdmissionProfile.version).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()

    resp = await _http_override(client, headers, profile_id, kv=kv, version=version)
    assert resp.status_code == 200, resp.text
    snap = await _read_snapshot_from_db(profile_id)
    assert snap["kv_resolved"] == kv, snap
    assert snap["rule_applied"] == "manual_override", snap
    return snap


# ===========================================================================
# 1 — override hợp lệ SỐNG qua freeze, KÈM dấu vết phê duyệt
# ===========================================================================


async def test_override_hop_le_song_qua_freeze(
    client, manager_token_headers, manager_user_in_db, submitted_profile,
):
    """Bất biến: freeze sau override hợp lệ giữ NGUYÊN KV + ai/khi nào/lý do.

    Trước bản vá: ``kv_resolved`` về ``None`` và ba khoá dấu vết biến mất
    (freeze dựng dict mới từ số 0).
    """
    pid = submitted_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")

    await _run_freeze(pid, frozen_at_status="engine_T6")
    snap = await _read_snapshot_from_db(pid)

    assert snap["kv_resolved"] == "KV1", (
        "Override hợp lệ bị freeze xoá mất KV — đúng lỗi B1. snapshot=%r" % snap
    )
    assert snap["rule_applied"] == "manual_override", snap
    assert snap["frozen_at_status"] == "engine_T6", snap
    # Dấu vết phê duyệt phải đi CÙNG giá trị, nếu không không ai đọc ra được
    # KV này từ đâu mà có.
    assert snap["manual_override_by"] == manager_user_in_db["id"], snap
    assert snap["manual_override_reason"] == OVERRIDE_REASON, snap
    assert snap.get("manual_override_at"), snap
    assert snap.get("manual_override_actor_role") == "manager", snap

    audit = await _latest_audit_row(pid)
    assert audit is not None
    assert snap["manual_override_audit_id"] == audit["id"], (
        "Snapshot phải trỏ về ĐÚNG hàng audit đã chứng minh nó."
    )


# ===========================================================================
# 2 — KV giữ được thì phải CHẤM ĐIỂM (đường im lặng 0đ)
# ===========================================================================


async def test_override_hop_le_van_cham_diem_khu_vuc(
    client, manager_token_headers, submitted_profile,
):
    """Bất biến: sau freeze, ``calculate_priority_bonus`` chấm theo KV1 (0.75đ).

    KV engine tự tính (KV3) có rate 0.00đ nên ca này KHÔNG thể xanh nhờ engine.
    """
    pid = submitted_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")
    await _run_freeze(pid, frozen_at_status="engine_T6")

    area, cfg = await _area_bonus_for(pid)
    assert cfg["area_code"] == "KV1", cfg
    assert area == KV1_RATE, (
        "Điểm khu vực = %s (kỳ vọng %s). 0đ ở đây là đường im lặng: "
        "_resolve_area_bonus thấy kv_resolved None thì return _ZERO." % (area, KV1_RATE)
    )
    assert area > Decimal("0")


# ===========================================================================
# 3 — lối vào thứ hai: PUT thường KHÔNG được bật manual_override
# ===========================================================================


async def test_put_thuong_khong_bat_duoc_manual_override(
    client, manager_token_headers, draft_profile,
):
    """Bất biến: ``PUT /api/admissions/{id}`` không bật được nhánh MANUAL.

    Trước bản vá: ``admission_service`` ghi thẳng cột, không kiểm, không audit.
    """
    pid = draft_profile["profile_id"]
    async with AsyncSessionLocal() as s:
        version = (
            await s.execute(
                select(models.AdmissionProfile.version).where(
                    models.AdmissionProfile.id == pid
                )
            )
        ).scalar_one()

    resp = await client.put(
        f"/api/admissions/{pid}",
        json={"version": version, "area_resolution_basis": "manual_override"},
        headers=manager_token_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "override-priority-kv" in resp.text

    async with AsyncSessionLocal() as s:
        basis = (
            await s.execute(
                select(models.AdmissionProfile.area_resolution_basis).where(
                    models.AdmissionProfile.id == pid
                )
            )
        ).scalar_one()
    assert basis != "manual_override", "Cột vẫn bị ghi dù request bị từ chối."


# ===========================================================================
# 4 — nhãn MANUAL đè lên snapshot ENGINE không phải chứng cứ
# ===========================================================================


async def test_nhan_manual_tren_snapshot_engine_khong_phai_chung_cu(
    draft_profile,
):
    """Bất biến: ``basis='manual_override'`` + snapshot do ENGINE tính ⇒ fail-closed.

    Đây là ca "rửa" nguy hiểm nhất nếu bản vá chỉ đơn giản giữ lại
    ``kv_resolved`` cũ: KV do engine tính (có thể từ dữ liệu đã sửa rồi đổi
    lại) được đóng dấu "thủ công" mà không ai duyệt.

    Cột được đặt THẲNG trong DB — cố tình bỏ qua cổng PUT ở ca 3 — để ca này
    chỉ khoá đúng MỘT bất biến: tầng freeze không tin cái nhãn.
    """
    from app.services.admission_service import _kv_unresolved_error_message

    pid = draft_profile["profile_id"]
    engine_snapshot = await _run_freeze(pid, frozen_at_status="submitted_T1")
    assert engine_snapshot["kv_resolved"] == "KV3"

    async with AsyncSessionLocal() as s:
        profile = await _load_profile(s, pid)
        profile.area_resolution_basis = "manual_override"
        await s.commit()

    snap = await _run_freeze(pid, frozen_at_status="submitted_T1")
    assert snap["kv_resolved"] is None, (
        "Nhãn MANUAL đã rửa được một KV engine tính ra: %r" % snap
    )
    assert snap["rule_applied"] == "manual_override_unverified", snap
    assert snap["requires_manual_override"] is True, snap
    assert snap["reason"].startswith("manual_override_unverified:"), snap
    # Guard submit CŨ (không sửa một chữ) phải chặn ca này.
    assert _kv_unresolved_error_message(snap, pid) is not None


# ===========================================================================
# 5 — dấu vết trong snapshot tự nó KHÔNG phải chứng cứ
# ===========================================================================


async def test_snapshot_day_du_nhung_khong_co_hang_audit_thi_fail_closed(
    client, manager_token_headers, submitted_profile,
):
    """Bất biến: thiếu hàng ``priority_audit_log`` ⇒ không công nhận.

    Snapshot ở đây có ĐỦ ``manual_override_by/_at/_reason`` và KV hợp lệ — tức
    là qua được mọi phép kiểm hình dạng. Chỉ hàng audit là không còn. Nếu tầng
    freeze tin snapshot thay vì đi tra sổ, ca này xanh oan.
    """
    pid = submitted_profile["profile_id"]
    snap_before = await _override_via_endpoint(
        client, manager_token_headers, pid, "KV1"
    )
    assert snap_before.get("manual_override_by")
    assert snap_before.get("manual_override_at")
    assert snap_before.get("manual_override_reason")

    async with AsyncSessionLocal() as s:
        await s.execute(
            delete(PriorityAuditLog).where(
                PriorityAuditLog.profile_id == pid,
                PriorityAuditLog.action_type == "kv_manual_override",
            )
        )
        await s.commit()
    assert await _latest_audit_row(pid) is None

    snap = await _run_freeze(pid, frozen_at_status="engine_T6")
    assert snap["kv_resolved"] is None, snap
    assert snap["rule_applied"] == "manual_override_unverified", snap
    assert snap["reason"] == "manual_override_unverified:no_audit_row", snap

    area, _cfg = await _area_bonus_for(pid)
    assert area == Decimal("0.00")


# ===========================================================================
# 6 — HẾT HIỆU LỰC khi đầu vào KV đổi
# ===========================================================================


async def test_override_het_hieu_luc_khi_du_lieu_kv_doi(
    client, manager_token_headers, submitted_profile,
):
    """Bất biến: sửa đầu vào KV sau khi duyệt ⇒ override hết hiệu lực.

    Người duyệt quyết trên MỘT bộ dữ liệu; đổi dữ liệu rồi vẫn giữ quyết định
    cũ là ký khống.
    """
    pid = submitted_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")

    async with AsyncSessionLocal() as s:
        profile = await _load_profile(s, pid)
        profile.permanent_commune_code = "OTHER_WARD_CODE"
        await s.commit()

    snap = await _run_freeze(pid, frozen_at_status="engine_T6")
    assert snap["kv_resolved"] is None, snap
    assert snap["reason"] == "manual_override_unverified:stale_inputs", snap


# ===========================================================================
# 7 — role ngoài {admin, manager} (hàng cũ trước Phase E.4 commit 7)
# ===========================================================================


async def test_hang_audit_role_officer_khong_duoc_cong_nhan(
    client, manager_token_headers, submitted_profile,
):
    """Bất biến: hàng audit do officer ghi (đường CŨ) không còn hợp lệ."""
    pid = submitted_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(PriorityAuditLog)
                .where(
                    PriorityAuditLog.profile_id == pid,
                    PriorityAuditLog.action_type == "kv_manual_override",
                )
                .order_by(PriorityAuditLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        meta = dict(row.audit_metadata or {})
        meta["actor_role"] = "officer"
        row.audit_metadata = meta
        await s.commit()

    snap = await _run_freeze(pid, frozen_at_status="engine_T6")
    assert snap["kv_resolved"] is None, snap
    assert snap["reason"] == "manual_override_unverified:actor_role_not_allowed", snap


# ===========================================================================
# 8 — hàng audit CŨ không có vân tay ⇒ fail-closed
# ===========================================================================


async def test_hang_audit_khong_co_van_tay_thi_fail_closed(
    client, manager_token_headers, submitted_profile,
):
    """Bất biến: không chứng minh được dữ liệu còn nguyên ⇒ không công nhận.

    Đây là hình dạng của MỌI hàng audit ghi TRƯỚC bản vá này. Lối ra vận hành
    là duyệt LẠI qua endpoint, không phải sửa dữ liệu cũ.
    """
    from app.services.priority_service import KV_INPUTS_FINGERPRINT_KEY

    pid = submitted_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(PriorityAuditLog)
                .where(
                    PriorityAuditLog.profile_id == pid,
                    PriorityAuditLog.action_type == "kv_manual_override",
                )
                .order_by(PriorityAuditLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        meta = dict(row.audit_metadata or {})
        meta.pop(KV_INPUTS_FINGERPRINT_KEY, None)
        row.audit_metadata = meta
        await s.commit()

    snap = await _run_freeze(pid, frozen_at_status="engine_T6")
    assert snap["kv_resolved"] is None, snap
    assert snap["reason"] == (
        "manual_override_unverified:provenance_incomplete_no_fingerprint"
    ), snap


# ===========================================================================
# 9 — ĐƯỜNG THẬT: evaluate_cascade (T6) giữ override và chấm điểm
# ===========================================================================


async def _seed_cascade_profile(
    seed_lead_dependencies: dict, *, status: str,
) -> dict:
    """Hồ sơ multi-NV thật: 1 NV, path bật ``apply_area_bonus``."""
    from tests.fixtures.builders import (
        AdmissionRoundBuilder,
        ensure_submittable_ward,
        seed_submittable_offering_config,
        submittable_profile_fields,
    )

    await ensure_submittable_ward()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            seed = await seed_submittable_offering_config(
                s, unit_id=seed_lead_dependencies["unit_id"],
                academic_year=ACADEMIC_YEAR,
            )
            await _seed_area_rates(s)

            ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=ACADEMIC_YEAR,
            )
            method = models.AdmissionMethod(
                code=f"B1M_{ts}",
                name=f"B1 method {ts}",
                requires_subject_scores=False,
                requires_gpa=False,
                is_active=True,
            )
            s.add(method)
            await s.flush()
            path = models.AdmissionPath(
                academic_info_id=seed["academic_info_id"],
                admission_method_id=method.id,
                admission_round_id=round_id,
                status="active",
                admit_quota=10,
                round_quota=10,
                # Bật KV bonus — đây là cái engine đọc ở T6.
                bonus_rule_override={
                    "apply_area_bonus": True,
                    "apply_object_bonus": False,
                },
            )
            s.add(path)
            await s.flush()

            sg = models.SubjectGroup(code=f"B1G{ts}"[:20], name=f"B1 grp {ts}")
            s.add(sg)
            await s.flush()
            config = models.PathSubjectGroupConfig(
                admission_path_id=path.id,
                subject_group_id=sg.id,
                min_score=Decimal("0.0"),
            )
            s.add(config)
            await s.flush()

            lead = models.Lead(
                full_name=f"B1 cascade lead {ts}",
                phone=f"08{ts:08d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            fields = submittable_profile_fields(seed)
            fields["uses_choice_engine"] = True
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"9{ts:08d}0"[:12],
                status=status,
                academic_year=ACADEMIC_YEAR,
                applied_rules={},
                **fields,
            )
            s.add(profile)
            await s.flush()
            choice = models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=path.id,
                path_subject_group_config_id=config.id,
                display_order=1,
                decision="pending",
            )
            s.add(choice)
            await s.flush()
            out = {
                "profile_id": profile.id,
                "choice_id": choice.id,
                "path_id": path.id,
            }
    return out


@pytest_asyncio.fixture
async def cascade_profile(seed_lead_dependencies: dict) -> dict:
    return await _seed_cascade_profile(seed_lead_dependencies, status="reviewing")


@pytest_asyncio.fixture
async def cascade_profile_submitted(seed_lead_dependencies: dict) -> dict:
    return await _seed_cascade_profile(seed_lead_dependencies, status="submitted")


async def _run_engine(profile_id: int, *, entry: str) -> None:
    """Gọi engine THẬT — ``entry`` chọn ``evaluate_cascade`` hay ``publish_result``.

    KHÔNG monkeypatch ``_evaluate_single_choice`` (mẫu quen thuộc ở
    ``tests/integration/test_choice_engine_quota_concurrent.py``): thứ đang
    nghiệm thu nằm NGAY TRƯỚC nó trong cùng vòng lặp — freeze T6 rồi
    ``calculate_priority_bonus`` — nên thay quyết định admit/reject bằng hàm giả
    sẽ che mất đúng đoạn cần đo.
    """
    from app.services import admission_choice_engine_service as engine_mod

    async with AsyncSessionLocal() as s:
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                selectinload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.academic_info),
                selectinload(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_method),
                selectinload(models.AdmissionProfile.choices)
                .selectinload(models.AdmissionProfileChoice.admission_path)
                .selectinload(models.AdmissionPath.admission_round),
            )
        )
        profile = (await s.execute(stmt)).scalar_one()
        if entry == "publish_result":
            await engine_mod.publish_result(s, profile)
        else:
            await engine_mod.evaluate_cascade(s, profile)
        await s.commit()


async def _assert_choice_scored_kv1(profile_id: int, choice_id: int, where: str):
    async with AsyncSessionLocal() as s:
        choice = (
            await s.execute(
                select(models.AdmissionProfileChoice).where(
                    models.AdmissionProfileChoice.id == choice_id
                )
            )
        ).scalar_one()
        area_snap = choice.priority_area_bonus_snapshot
        cfg_snap = dict(choice.priority_config_snapshot or {})

    snap = await _read_snapshot_from_db(profile_id)
    assert snap["kv_resolved"] == "KV1", (
        "Freeze T6 trong %s đã xoá override: %r" % (where, snap)
    )
    assert snap["frozen_at_status"] == "engine_T6", snap
    assert cfg_snap.get("area_code") == "KV1", cfg_snap
    assert area_snap is not None and Decimal(area_snap) == KV1_RATE, (
        "priority_area_bonus_snapshot = %r (kỳ vọng %s)" % (area_snap, KV1_RATE)
    )
    assert Decimal(area_snap) > Decimal("0")


async def test_cascade_t6_giu_override_va_cham_diem_khu_vuc(
    client, manager_token_headers, cascade_profile,
):
    """Bất biến: sau ``evaluate_cascade`` THẬT, NV giữ điểm khu vực > 0.

    Freeze T6 nằm NGAY TRƯỚC ``calculate_priority_bonus`` trong cùng vòng lặp,
    nên đây chính là chỗ override bị xoá rồi chấm 0đ.
    """
    pid = cascade_profile["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")
    await _run_engine(pid, entry="evaluate_cascade")
    await _assert_choice_scored_kv1(
        pid, cascade_profile["choice_id"], "evaluate_cascade",
    )


async def test_publish_result_giu_override_va_cham_diem_khu_vuc(
    client, manager_token_headers, cascade_profile_submitted,
):
    """Bất biến: cùng kết luận qua ĐÚNG entrypoint router gọi — ``publish_result``.

    ``publish_result`` thêm các cổng tiền-điều-kiện (đổi ngành, nợ giấy tờ) và
    tự chuyển submitted -> reviewing rồi mới ``evaluate_cascade``. Ca này đi hết
    chuỗi đó với dữ liệu thật để lời khẳng định không dừng ở "hàm bên trong
    đúng".
    """
    pid = cascade_profile_submitted["profile_id"]
    await _override_via_endpoint(client, manager_token_headers, pid, "KV1")
    await _run_engine(pid, entry="publish_result")
    await _assert_choice_scored_kv1(
        pid, cascade_profile_submitted["choice_id"], "publish_result",
    )


# ===========================================================================
# 10 — chứng minh KHÔNG nới guard KV_UNRESOLVED
# ===========================================================================


async def test_draft_van_duyet_lai_duoc_sau_khi_override_het_hieu_luc(
    client, manager_token_headers, draft_profile_kv_unresolvable,
):
    """Bất biến: hồ sơ draft đã override vẫn duyệt LẠI được (không khoá cứng).

    Bản vá B1 biến "hết hiệu lực" thành đường vận hành thường gặp
    (``stale_inputs``), nên lối ra phải tồn tại. Cổng override-draft cũ đọc mỗi
    ``requires_manual_override`` nên coi nhánh MANUAL (engine trả None, KHÔNG
    tính ra gì) là "engine tự xử được" và trả 400 cho mọi lần override thứ hai.
    Fail-closed mà không có lối ra là ngõ cụt, không phải an toàn.
    """
    pid = draft_profile_kv_unresolvable["profile_id"]

    # Tiền đề: engine THẬT SỰ không xác định được ⇒ cổng draft mở cho lần 1.
    snap0 = await _run_freeze(pid, frozen_at_status="submitted_T1")
    assert snap0["rule_applied"] == "catalog_gap_school", snap0
    assert snap0["requires_manual_override"] is True, snap0

    async def _version() -> int:
        async with AsyncSessionLocal() as s:
            return (
                await s.execute(
                    select(models.AdmissionProfile.version).where(
                        models.AdmissionProfile.id == pid
                    )
                )
            ).scalar_one()

    r1 = await _http_override(
        client, manager_token_headers, pid, kv="KV1", version=await _version(),
    )
    assert r1.status_code == 200, r1.text

    r2 = await _http_override(
        client, manager_token_headers, pid, kv="KV2-NT", version=await _version(),
        reason="Duyet lai sau khi ho so bo sung giay to xac minh khu vuc moi.",
    )
    # Ca này CHỈ khoá bất biến "còn lối duyệt lại". Việc giá trị mới sống qua
    # freeze do ca 1 khoá — trộn vào đây thì một lần đỏ không nói lên cái gì.
    assert r2.status_code == 200, (
        "Override lần 2 trên hồ sơ draft bị từ chối — ngõ cụt: %s" % r2.text
    )


def test_guard_kv_unresolved_khong_bi_noi():
    """Bất biến: whitelist thành công của cổng submit KHÔNG đổi.

    Bản vá B1 đi ra bằng một ``rule_applied`` NGOÀI whitelist thay vì thêm giá
    trị vào whitelist — đây là phép kiểm nói lên điều đó.
    """
    from app.services.admission_service import _KV_SUCCESS_RULE_APPLIED
    from app.services.priority_service import _MANUAL_OVERRIDE_UNVERIFIED_RULE

    assert _KV_SUCCESS_RULE_APPLIED == frozenset({
        "longest_duration",
        "tiebreak_graduation_school",
        "commune_lookup",
        "manual_override",
    })
    assert _MANUAL_OVERRIDE_UNVERIFIED_RULE not in _KV_SUCCESS_RULE_APPLIED


# ===========================================================================
# 11 — nhánh anh em: ut_verified_bucket cũng bị freeze dựng lại làm rơi
# ===========================================================================


async def test_freeze_giu_ut_verified_bucket(draft_profile):
    """Bất biến: khoá do đường verify chứng cứ UT ghi vào CÙNG cột JSONB
    không bị freeze thổi bay.

    ``priority_override_service`` (verify/reject/untick) ghi
    ``ut_verified_bucket`` bằng deep-merge; freeze dựng dict mới nên nó rơi mất
    — cùng một lớp lỗi với override KV.
    """
    pid = draft_profile["profile_id"]
    await _run_freeze(pid, frozen_at_status="submitted_T1")

    bucket = {"applied_code": "06", "applied_rate": "1.00"}
    async with AsyncSessionLocal() as s:
        profile = await _load_profile(s, pid)
        snapshot = dict(profile.priority_resolution_snapshot or {})
        snapshot["ut_verified_bucket"] = bucket
        profile.priority_resolution_snapshot = snapshot
        await s.commit()

    snap = await _run_freeze(pid, frozen_at_status="engine_T6")
    assert snap.get("ut_verified_bucket") == bucket, snap
