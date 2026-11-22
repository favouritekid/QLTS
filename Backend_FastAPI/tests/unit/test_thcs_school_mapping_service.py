# -*- coding: utf-8 -*-
"""Công cụ ghép tên trường THCS gõ tay (owner 22-11, đề xuất Phần B) — phần chạy trên CSDL thật.

Mỗi bất biến một ca (CLAUDE.md chung §3):

* gom nhóm theo tên chuẩn hoá, bỏ hồ sơ rút, bỏ dòng đã có trường, KHÔNG trả dữ liệu cá nhân;
* ghép chỉ với trường THCS / liên cấp đang hoạt động; một tên ghép một trường; huỷ ghép có vết;
* tạo trường mới từ nhóm đi qua đúng luật mã nội bộ NB + mã xã;
* áp ghép: chạy thử không ghi; chạy thật khoá bằng cờ CHO PHÉP (tắt ⇒ 409, không ghi gì); chỉ gắn dòng THCS gõ tay
  khớp tên, ở hồ sơ chờ xét, không gắn Quyết định; đối chiếu số với lượt chạy thử; tăng ``version``; ghi vết từng hồ sơ;
  báo trước số hồ sơ KV ấn định tay và số dòng y→y.

Hồ sơ giả chèn bằng SQL thô (``tests/fixtures/hoi_dong_seed.chen``) — chỉ các cột bắt buộc.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.entity_audit_log import EntityAuditLog
from app.models.thcs_school_name_mapping import ThcsSchoolNameMapping
from app.models.vn_locality import VnCommuneAreaMap
from app.services import thcs_school_mapping_service as svc_mod
from app.services.council_decision_status_service import HAS_EFFECTIVE_DECISION, DecisionState
from app.services.thcs_school_mapping_service import ThcsSchoolMappingService
from app.services.vn_school_service import VnSchoolService
from app.models.user import User
from app.services import admission_service
from app.utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
    ProfileVersionConflict,
    ResourceNotFoundError,
)
from app.utils.exceptions import ValidationError as DomainValidationError
from tests.fixtures.hoi_dong_seed import LUC, chen, ma_gia

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest.fixture
def cho_phep_ap(monkeypatch):
    """Bật ``THCS_MAPPING_APPLY_ENABLED`` cho đúng một test (patch thẳng ``settings`` — xem ``cho_phep_dong_ky``)."""
    monkeypatch.setattr(settings, "THCS_MAPPING_APPLY_ENABLED", True)
    return True


@pytest.fixture
def khoa_ap(monkeypatch):
    monkeypatch.setattr(settings, "THCS_MAPPING_APPLY_ENABLED", False)
    return False


def _thcs(ten, y_from, y_to=None, **kw) -> dict:
    return {
        "school_id": kw.get("school_id"),
        "school_name": ten,
        "level": kw.get("level"),
        "year_from": y_from,
        "year_to": y_from if y_to is None else y_to,
        "grade_to": kw.get("grade_to"),
        "gpa": None,
        "graduation_type": kw.get("graduation_type", "THCS"),
    }


def _thpt(ten="THPT Thử", school_id=None) -> dict:
    return {"school_id": school_id, "school_name": ten, "level": "THPT", "year_from": 2023, "year_to": 2025,
            "grade_to": 12, "gpa": None, "graduation_type": "THPT"}


class _Nen:
    def __init__(self, db):
        self.db = db
        self.so = 0

    async def dung(self):
        self.unit = await chen(self.db, "organization_unit", name="Đơn vị thử THCS", type="department")
        self.admin = await chen(
            self.db, "user", username="thcs_ghep_admin", email="thcs_ghep_admin@example.invalid",
            password_hash="x", role="admin", total_lead_score=0,
        )
        self.db.add(VnCommuneAreaMap(commune_code="99201", province="Tỉnh Thử", district="", ward="Xã Thử",
                                     area_code="KV1"))
        await self.db.flush()
        return self

    async def ho_so(self, lich_su, status="submitted", basis=None, nam=2026) -> int:
        self.so += 1
        lead = await chen(
            self.db, "lead", full_name="Lead giả", phone="0000000000", source="gia", status="new",
            assignment_status="pending", lead_score=0, location_proximity=0, occupation_relevance=0,
            academic_performance=0, created_at=LUC, updated_at=LUC, version=1, consultation_count=0,
            cached_urgency_score=0, is_hot_lead=False, is_overdue=False, unit_id=self.unit,
        )
        cot = dict(lead_id=lead, academic_year=nam, citizen_id=ma_gia(71000 + self.so), applied_rules={},
                   created_at=LUC, updated_at=LUC, status=status, uses_choice_engine=False,
                   academic_history=lich_su)
        if basis:
            cot["area_resolution_basis"] = basis
        return await chen(self.db, "admission_profile", **cot)

    async def truong_noi_bo(self, ten="THCS Lê Lợi (danh mục)", level="THCS"):
        s, _ = await VnSchoolService(self.db).create_school(
            {"moet_province_code": "048", "name": ten, "province": "Tỉnh Thử", "level": level,
             "commune_code": "99201"}
        )
        await self.db.flush()
        return s

    async def lich_su(self, pid):
        return (await self.db.execute(
            text("SELECT academic_history FROM admission_profile WHERE id = :p"), {"p": pid}
        )).scalar_one()

    async def version(self, pid):
        return (await self.db.execute(
            text("SELECT version FROM admission_profile WHERE id = :p"), {"p": pid}
        )).scalar_one()


@pytest_asyncio.fixture
async def nen(db):
    return await _Nen(db).dung()


# =====================================================================================================================
# Gom nhóm
# =====================================================================================================================


async def test_gom_nhom_theo_ten_chuan_hoa_bo_ho_so_rut_va_dong_da_co_truong(db, nen) -> None:
    await nen.ho_so([_thcs("Trường THCS Lê Lợi", 2018), _thcs("Trường THCS Lê Lợi", 2019), _thpt()])
    await nen.ho_so([_thcs("THCS  Lê Lợi.", 2018, 2021)], status="draft")
    await nen.ho_so([_thcs("THCS Nguyễn Du", 2020, level="THCS", graduation_type=None)])
    await nen.ho_so([_thcs("THCS Lê Lợi", 2018)], status="withdrawn")  # rút ⇒ không tính
    await nen.ho_so([_thcs("THCS Lê Lợi", 2018, school_id=999)])  # đã gắn trường ⇒ không tính
    await nen.ho_so([_thcs("   ", 2018)])  # tên trống
    kq = await ThcsSchoolMappingService(db).list_groups()
    nhom = {g["normalized_name"]: g for g in kq["items"]}
    assert set(nhom) == {"lê lợi", "nguyễn du"}
    ll = nhom["lê lợi"]
    # Owner 22-11 câu 1: nháp CŨNG thuộc phạm vi áp ghép ⇒ cả hai hồ sơ (submitted + draft, năm 2026) đều tính.
    assert (ll["row_count"], ll["profile_count"], ll["eligible_profile_count"], ll["same_year_row_count"]) == (3, 2, 2, 2)
    assert {v["text"]: v["row_count"] for v in ll["variants"]} == {"Trường THCS Lê Lợi": 2, "THCS Lê Lợi.": 1}
    assert ll["mapping"] is None
    assert kq["summary"]["blank_name_row_count"] == 1
    # Không có dữ liệu cá nhân: không id hồ sơ, không CCCD, không tên thí sinh.
    blob = json.dumps(kq, default=str, ensure_ascii=False)
    assert ma_gia(71001) not in blob and "Lead giả" not in blob and "profile_id" not in blob


async def test_gom_nhom_loc_da_ghep_chua_ghep_va_phan_trang(db, nen) -> None:
    s = await nen.truong_noi_bo()
    for ten in ("THCS A", "THCS B", "THCS C"):
        await nen.ho_so([_thcs(ten, 2018)])
    svc = ThcsSchoolMappingService(db)
    await svc.map_group("a", s.id, nen.admin)
    assert [g["normalized_name"] for g in (await svc.list_groups(mapped=True))["items"]] == ["a"]
    assert {g["normalized_name"] for g in (await svc.list_groups(mapped=False))["items"]} == {"b", "c"}
    trang = await svc.list_groups(page=2, page_size=2)
    assert (trang["total"], len(trang["items"])) == (3, 1)


# =====================================================================================================================
# Ghép / huỷ ghép / tạo trường từ nhóm
# =====================================================================================================================


async def test_ghep_chi_voi_truong_thcs_dang_hoat_dong(db, nen) -> None:
    svc = ThcsSchoolMappingService(db)
    thpt, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "040900", "moet_province_code": "048", "name": "THPT X", "province": "P", "level": "THPT"}
    )
    await db.flush()
    with pytest.raises(BusinessRuleViolation, match="cấp THCS hoặc liên cấp"):
        await svc.map_group("lê lợi", thpt.id, nen.admin)
    s = await nen.truong_noi_bo()
    await VnSchoolService(db).deactivate_school(s.id)
    await db.flush()
    with pytest.raises(BusinessRuleViolation, match="ngừng"):
        await svc.map_group("lê lợi", s.id, nen.admin)
    with pytest.raises(ResourceNotFoundError):
        await svc.map_group("lê lợi", 987654, nen.admin)


async def test_ghep_mot_ten_mot_truong_va_khoa_phai_chuan_hoa(db, nen) -> None:
    svc = ThcsSchoolMappingService(db)
    s = await nen.truong_noi_bo()
    row = await svc.map_group("lê lợi", s.id, nen.admin)
    assert (row.normalized_name, row.school_id, row.mapped_by_user_id) == ("lê lợi", s.id, nen.admin)
    with pytest.raises(ConflictError, match="đã ghép"):
        await svc.map_group("lê lợi", s.id, nen.admin)
    with pytest.raises(DomainValidationError, match="chuẩn hoá"):
        await svc.map_group("Trường THCS Nguyễn Du", s.id, nen.admin)


async def test_huy_ghep_xoa_dong_va_ghi_vet(db, nen) -> None:
    svc = ThcsSchoolMappingService(db)
    s = await nen.truong_noi_bo()
    row = await svc.map_group("lê lợi", s.id, nen.admin)
    await svc.unmap_group("lê lợi", nen.admin)
    assert (await db.execute(select(ThcsSchoolNameMapping))).scalars().all() == []
    with pytest.raises(ResourceNotFoundError):
        await svc.unmap_group("lê lợi", nen.admin)
    vet = (await db.execute(
        select(EntityAuditLog.action).where(EntityAuditLog.entity_type == "ThcsSchoolNameMapping",
                                            EntityAuditLog.entity_id == row.id)
        .order_by(EntityAuditLog.id)
    )).scalars().all()
    assert vet == ["mapped", "unmapped"]


async def test_tao_truong_moi_tu_nhom_di_qua_luat_ma_noi_bo(db, nen) -> None:
    svc = ThcsSchoolMappingService(db)
    truong = {"moet_province_code": "048", "name": "THCS Lê Lợi", "province": "Tỉnh Thử", "level": "THCS",
              "commune_code": "99201", "is_dtnt": False}
    with pytest.raises(DomainValidationError, match="mã nội bộ NB"):
        await svc.create_school_from_group("lê lợi", {**truong, "moet_school_code": "040123"}, nen.admin)
    with pytest.raises(DomainValidationError, match="bắt buộc chọn xã"):
        await svc.create_school_from_group("lê lợi", {**truong, "commune_code": None}, nen.admin)
    school, m = await svc.create_school_from_group("lê lợi", truong, nen.admin)
    assert school.moet_school_code.startswith("NB") and len(school.moet_school_code) == 8
    assert (m.normalized_name, m.school_id) == ("lê lợi", school.id)


# =====================================================================================================================
# Áp ghép
# =====================================================================================================================


async def _bo_du_lieu_ap(db, nen):
    s = await nen.truong_noi_bo()
    ids = {
        # 3 dòng y→y (nút cũ) + 1 dòng y→y chỉ có level=THCS (không graduation_type) + dòng THPT (không chạm)
        "p1": await nen.ho_so([_thcs("THCS Lê Lợi", y) for y in (2017, 2018, 2019)]
                              + [_thcs("Trường THCS Lê Lợi", 2020, level="THCS", graduation_type=None), _thpt()]),
        "p2": await nen.ho_so([_thcs("THCS Lê Lợi", 2016, 2020)], status="reviewing", basis="manual_override"),
        "p3": await nen.ho_so([_thcs("THCS Lê Lợi", 2018)], status="draft"),  # nháp: ĐƯỢC chạm (owner câu 1)
        "p4": await nen.ho_so([_thcs("THCS Lê Lợi", 2018)], status="result_published"),
        "p5": await nen.ho_so([_thcs("THCS Chưa Ghép", 2018)]),
        "p6": await nen.ho_so([_thcs("THCS Lê Lợi", 2018, school_id=777, level="THCS")]),
        "p7": await nen.ho_so([_thcs("THCS Lê Lợi", 2018)], status="withdrawn"),
        "p8": await nen.ho_so([_thcs("THCS Lê Lợi", 2018)], nam=2025),  # năm khác ⇒ không chạm (owner câu 2)
    }
    await ThcsSchoolMappingService(db).map_group("lê lợi", s.id, nen.admin)
    return s, ids


async def test_chay_thu_dem_dung_va_khong_ghi_gi(db, nen) -> None:
    _s, ids = await _bo_du_lieu_ap(db, nen)
    truoc = {k: await nen.lich_su(v) for k, v in ids.items()}
    kq = await ThcsSchoolMappingService(db).apply_mappings(dry_run=True, actor_id=nen.admin)
    assert kq["applied"] is False and kq["dry_run"] is True
    assert (kq["rows_to_change"], kq["profiles_to_change"]) == (6, 3)
    assert (kq["draft_rows_to_change"], kq["draft_profiles_to_change"]) == (1, 1)  # báo riêng hồ sơ nháp
    assert (kq["same_year_rows"], kq["same_year_profiles"]) == (5, 2)
    assert kq["manual_kv_override_profiles"] == 1
    assert (kq["skipped_status_profiles"], kq["skipped_status_rows"]) == (1, 1)  # có kết quả
    assert (kq["skipped_year_profiles"], kq["skipped_year_rows"]) == (1, 1)  # năm 2025
    assert kq["academic_year"] == 2026 and "draft" in kq["eligible_statuses"]
    assert kq["unmapped_rows"] == 1
    assert kq["skipped_decision_profiles"] == 0 and kq["unusable_mappings"] == 0
    assert {k: await nen.lich_su(v) for k, v in ids.items()} == truoc


async def test_chay_that_khi_co_tat_thi_409_khong_ghi_gi(db, nen, khoa_ap) -> None:
    _s, ids = await _bo_du_lieu_ap(db, nen)
    truoc = {k: (await nen.lich_su(v), await nen.version(v)) for k, v in ids.items()}
    with pytest.raises(ConflictError) as e:
        await ThcsSchoolMappingService(db).apply_mappings(
            dry_run=False, actor_id=nen.admin, expected_rows_to_change=6, expected_profiles_to_change=3
        )
    assert e.value.public_payload == {"operation": "thcs_mapping_apply", "reason": "apply_disabled"}
    assert {k: (await nen.lich_su(v), await nen.version(v)) for k, v in ids.items()} == truoc
    so_vet = (await db.execute(
        select(EntityAuditLog).where(EntityAuditLog.action == "thcs_school_mapping_applied")
    )).scalars().all()
    assert so_vet == []


async def test_chay_that_chi_gan_dong_thcs_go_tay_khop_ten_o_ho_so_cho_xet(db, nen, cho_phep_ap) -> None:
    s, ids = await _bo_du_lieu_ap(db, nen)
    truoc = {k: (await nen.lich_su(v), await nen.version(v)) for k, v in ids.items()}
    svc = ThcsSchoolMappingService(db)
    kq = await svc.apply_mappings(dry_run=False, actor_id=nen.admin, expected_rows_to_change=6,
                                  expected_profiles_to_change=3)
    assert kq["applied"] is True and kq["apply_enabled"] is True
    p1 = await nen.lich_su(ids["p1"])
    assert [(r["school_id"], r["level"]) for r in p1[:4]] == [(s.id, "THCS")] * 4
    assert p1[4] == truoc["p1"][0][4]  # dòng THPT nguyên vẹn
    assert [r["school_name"] for r in p1[:4]] == [r["school_name"] for r in truoc["p1"][0][:4]]  # tên gốc giữ
    assert (await nen.lich_su(ids["p2"]))[0]["school_id"] == s.id
    assert (await nen.lich_su(ids["p3"]))[0]["school_id"] == s.id  # nháp
    for k in ("p1", "p2", "p3"):
        assert await nen.version(ids[k]) == truoc[k][1] + 1
    for k in ("p4", "p5", "p6", "p7", "p8"):
        assert (await nen.lich_su(ids[k]), await nen.version(ids[k])) == truoc[k], k
    vet = (await db.execute(
        select(EntityAuditLog).where(EntityAuditLog.action == "thcs_school_mapping_applied")
        .order_by(EntityAuditLog.entity_id)
    )).scalars().all()
    assert [(v.entity_type, v.entity_id, v.actor_user_id) for v in vet] == [
        ("AdmissionProfile", ids["p1"], nen.admin), ("AdmissionProfile", ids["p2"], nen.admin),
        ("AdmissionProfile", ids["p3"], nen.admin),
    ]
    assert [r["index"] for r in vet[0].new_value] == [0, 1, 2, 3]
    # Chạy lại: không còn gì để gắn (lũy đẳng).
    lai = await svc.apply_mappings(dry_run=True)
    assert (lai["rows_to_change"], lai["profiles_to_change"]) == (0, 0)


async def test_chay_that_so_lech_voi_chay_thu_thi_409_khong_ghi_gi(db, nen, cho_phep_ap) -> None:
    _s, ids = await _bo_du_lieu_ap(db, nen)
    truoc = {k: await nen.lich_su(v) for k, v in ids.items()}
    with pytest.raises(ConflictError) as e:
        await ThcsSchoolMappingService(db).apply_mappings(
            dry_run=False, actor_id=nen.admin, expected_rows_to_change=5, expected_profiles_to_change=3
        )
    assert e.value.public_payload["reason"] == "preview_mismatch"
    assert {k: await nen.lich_su(v) for k, v in ids.items()} == truoc


async def test_chay_that_thieu_so_cua_chay_thu_thi_tu_choi(db, nen, cho_phep_ap) -> None:
    await _bo_du_lieu_ap(db, nen)
    with pytest.raises(DomainValidationError, match="lượt chạy thử"):
        await ThcsSchoolMappingService(db).apply_mappings(dry_run=False, actor_id=nen.admin)


async def test_bo_qua_ho_so_gan_quyet_dinh(db, nen, monkeypatch) -> None:
    _s, ids = await _bo_du_lieu_ap(db, nen)

    async def _gia(_db, profile_ids, *, lock=False):
        return {pid: DecisionState(HAS_EFFECTIVE_DECISION, qd_hieu_luc_id=1) for pid in profile_ids if pid == ids["p2"]}

    monkeypatch.setattr(svc_mod, "decision_state", _gia)
    kq = await ThcsSchoolMappingService(db).apply_mappings(dry_run=True)
    assert kq["skipped_decision_profiles"] == 1
    assert (kq["rows_to_change"], kq["profiles_to_change"]) == (5, 2)
    assert kq["manual_kv_override_profiles"] == 0  # p2 bị bỏ qua ⇒ không còn tính


async def test_ghep_tro_truong_da_ngung_thi_khong_dung(db, nen) -> None:
    s, _ids = await _bo_du_lieu_ap(db, nen)
    await VnSchoolService(db).deactivate_school(s.id)
    await db.flush()
    kq = await ThcsSchoolMappingService(db).apply_mappings(dry_run=True)
    assert kq["unusable_mappings"] == 1
    assert (kq["rows_to_change"], kq["profiles_to_change"]) == (0, 0)



async def test_can_bo_luu_form_nhap_cu_sau_ap_ghep_nhan_cau_xung_dot_ro_rang(db, nen, cho_phep_ap) -> None:
    """Owner 22-11 câu 1: áp ghép tăng ``version`` của hồ sơ NHÁP ⇒ cán bộ đang mở form (giữ ``version`` cũ) mà lưu thì
    BỊ CHẶN bằng ``ProfileVersionConflict`` (mã riêng, câu tiếng Việt) — không ghi đè lịch sử học vừa gắn trường."""
    s, ids = await _bo_du_lieu_ap(db, nen)
    v_cu = await nen.version(ids["p3"])
    await ThcsSchoolMappingService(db).apply_mappings(
        dry_run=False, actor_id=nen.admin, expected_rows_to_change=6, expected_profiles_to_change=3
    )
    admin = await db.get(User, nen.admin)
    with pytest.raises(ProfileVersionConflict) as e:
        await admission_service.update_profile(
            db, ids["p3"], {"version": v_cu, "academic_history": [_thcs("THCS Lê Lợi", 2018)]}, admin
        )
    assert e.value.error_code == "PROFILE_VERSION_CONFLICT"
    assert "Tải lại trang hồ sơ" in e.value.detail
    assert e.value.public_payload == {"current_version": v_cu + 1}
    assert (await nen.lich_su(ids["p3"]))[0]["school_id"] == s.id  # không bị ghi đè
