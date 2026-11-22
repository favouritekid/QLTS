# -*- coding: utf-8 -*-
"""GĐ2-B lát L2 — luật THUẦN của máy xét mới (không CSDL): E1–E7, ưu tiên v2, xét nguyện vọng, xếp Q1, bốn tab + mã, ``row_hash``,
``quota_view``, cảnh báo / cờ (A13 theo K4 + biên bản A13 21-11; A19 theo phụ lục điểm 1).

Nguồn: biên bản owner K1–K4 21-11 + A13 21-11 > QĐB / QĐO1 / QĐH1 20-11 > đặc tả GĐ2-B bản 4 §6, §9.4, §10, §11 + hợp đồng API bản 4
§3.5, §4. Mỗi ca kiểm MỘT bất biến trên một hồ sơ SẠCH (mặc định: Kinh, học bạ bắt buộc đã duyệt, học phí + lệ phí đã đóng, một NV
vào học vụ 41 chỉ tiêu 10, sàn 15,00, điểm 15,00 + KV 0,75 ⇒ ``auto``). Ca CSDL thật / API thuộc đợt 2 (L3b, L5).
"""
import dataclasses
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import admission_review_rules as R
from app.services import council_set_gate_service as cong
from app.services import fee_gate_rules as fg
from app.services import quota_occupancy_service as qos
from app.services.admission_choice_engine_service import ChoiceGateOutcome
from app.services.admission_scoring_service import AdmissionScoreResult, ProfileStatus
from app.services.admission_state_machine import AdmissionStatus
from app.services.council_document_render_service import compute_printed_scores
from app.services.document_review_rules import (
    DOCUMENT_CONFIG_INVALID,
    DOCUMENT_CONFIG_MISSING,
    required_document_codes,
)
from app.utils.exceptions import (
    BadRequest,
    ChoiceTargetLevelNotConfigured,
    PriorityRateNotConfigured,
    ServiceUnavailableError,
)

pytestmark = pytest.mark.unit

NAM = 2026
HV1, HV2, HV3 = 41, 57, 63
NHOM = 7
HOC_BA = "hoc_ba_thpt"
KHAI_SINH = R.BIRTH_CERTIFICATE_DOC_CODE
CU_TRU = R.RESIDENCE_PROOF_DOC_CODE


# ═══════════════════════════════════════════ dựng dữ kiện SẠCH ═══════════════════════════════════════════
def _hv(ai_id, **kw):
    goc = dict(
        offering_academic_info_id=ai_id,
        academic_year=NAM,
        offering_id=ai_id + 1000,
        annual_quota=10,
        group_id=NHOM,
        major_code="M%d" % ai_id,
        major_name="Ngành %d" % ai_id,
        offering_type="Chính quy",
    )
    goc.update(kw)
    return R.AcademicInfoFacts(**goc)


def _run(*, hv=None, floors=None, **kw):
    goc = dict(
        academic_year=NAM,
        fee_gate_mode=fg.FEE_GATE_MODE_LEGACY,
        floors={HV1: D("15.00"), HV2: D("15.00"), HV3: D("15.00")} if floors is None else floors,
        academic_infos={HV1: _hv(HV1), HV2: _hv(HV2), HV3: _hv(HV3)} if hv is None else hv,
        groups=(R.GroupFacts(NHOM, "N1", "Nhóm 1", ceiling=100),),
        quota_table_status="locked",
        object_rates={"01": D("2.00"), "06": D("1.00"), "03": D("1.00"), "04": D("1.50")},
    )
    goc.update(kw)
    return R.RunFacts(**goc)


def _check(**kw):
    goc = dict(
        stt=1,
        status="submitted",
        uses_choice_engine=True,
        so_nv=1,
        nv1_id=None,
        nv_in_id=None,
        so_nv_trung=0,
        nv_trung_id=None,
        hp_co=True,
        hp_nganh_id=5,
        nv_in_nganh_id=None,
        nv_in_path_id=None,
        nv_in_sg_id=None,
        lg_nganh_id=None,
        lg_path_id=None,
        lg_sg_id=None,
        diem_ca_hai_khac=0,
        diem_chi_nv=0,
        diem_chi_hs=0,
        kv_ly_do=None,
        kv_muc="0.75",
        luat_kv=cong.AREA_RULE_ADD,
        luat_ut=cong.AREA_RULE_ADD,
    )
    goc.update(kw)
    return cong.CheckData(**goc)


def _nv(cid, order, ai, **kw):
    goc = dict(
        cid=cid,
        order=order,
        ai=ai,
        path_id=88,
        major_id=5,
        gate=R.GATE_PASSED,
        gate_codes=(),
        subject_total=D("15.00"),
        fee_free=True,
        area_rule=cong.AREA_RULE_ADD,
        object_rule=cong.AREA_RULE_ADD,
        score_both_differ=0,
    )
    goc.update(kw)
    return goc


def _quy_tac(mandatory=(HOC_BA,), optional=(CU_TRU,)):
    cfg = {c: {"is_mandatory": True, "requires_upload": True, "label": "Giấy %s" % c} for c in mandatory}
    cfg.update({c: {"is_mandatory": False, "requires_upload": False, "label": "Giấy %s" % c} for c in optional})
    return {"mandatory_docs": list(mandatory), "doc_configs": cfg, "min_gpa": None}


def _giay(doc_id=1, status="verified", row_version=1, verified_format="ban_sao"):
    return R.DocumentRowFacts(doc_id, status, row_version, verified_format)


_MAC_DINH = object()


def _ho_so(
    pid=1001,
    *,
    status="submitted",
    nvs=None,
    tuition=_MAC_DINH,
    app_fees=(R.FeeFacts(8001, "paid", D("30000")),),
    applied_rules=_MAC_DINH,
    docs=_MAC_DINH,
    ethnicity="Kinh",
    commune="01234",
    area="KV2",
    object_codes=(),
    prior=(),
    **check_kw,
):
    nvs = [_nv(501, 1, HV1)] if nvs is None else nvs
    hp = R.FeeFacts(9001, "paid", D("5000000")) if tuition is _MAC_DINH else tuition
    check = _check(status=status, so_nv=len(nvs), hp_co=hp is not None, **check_kw)
    choices = tuple(
        R.ChoiceFacts(
            choice_id=n["cid"],
            display_order=n["order"],
            admission_path_id=n["path_id"],
            offering_academic_info_id=n["ai"],
            major_id=n["major_id"],
            gate=R.ChoiceGateFacts(n["gate"], tuple(n["gate_codes"])),
            check=R.choice_check(
                check,
                choice_id=n["cid"],
                major_id=n["major_id"],
                admission_path_id=n["path_id"],
                subject_group_id=3,
                offering_academic_info_id=n["ai"],
                offering_id=(n["ai"] + 1000) if n["ai"] is not None else None,
                area_rule=n["area_rule"],
                object_rule=n["object_rule"],
                score_both_differ=n["score_both_differ"],
            ),
            subject_total=n["subject_total"],
            application_fee_free=n["fee_free"],
        )
        for n in nvs
    )
    return R.ProfileFacts(
        profile_id=pid,
        status=status,
        check=check,
        tuition_fee=hp,
        application_fees=tuple(app_fees),
        applied_rules=_quy_tac() if applied_rules is _MAC_DINH else applied_rules,
        path_documents={HOC_BA: _giay()} if docs is _MAC_DINH else docs,
        ethnicity_name=ethnicity,
        permanent_commune_code=commune,
        commune_area_code=area,
        verified_object_codes=tuple(object_codes),
        choices=choices,
        prior_year_profiles=tuple(prior),
    )


def _chay(*ho_so, run=None):
    return R.evaluate_run(list(ho_so), run or _run())


def _dong(ho_so, run=None):
    rows = _chay(ho_so, run=run).rows
    assert len(rows) == 1
    return rows[0]


def _dtts(**kw):
    """Hồ sơ em dân tộc thiểu số SẠCH: khai sinh (KHÔNG bắt buộc) + giấy cư trú đã duyệt, xã KV1."""
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2), CU_TRU: _giay(3)}
    goc = dict(ethnicity="Tày", docs=docs, area="KV1", applied_rules=_quy_tac(optional=(CU_TRU, KHAI_SINH)))
    goc.update(kw)
    return _ho_so(**goc)


def test_ho_so_sach_vao_tab_dat_may_de_xuat():
    dong = _dong(_ho_so())
    assert (dong.tab, dong.reason_codes, dong.considered.choice_id, dong.within_seats) == (R.TAB_AUTO, (), 501, True)


# ═══════════════════════════════════════════ E1 — tập xét (BT01, BT02) ═══════════════════════════════════════════
@pytest.mark.parametrize("trang_thai", R.POOL_STATUSES)
def test_ba_trang_thai_cua_tap_xet_duoc_xet(trang_thai):
    assert _dong(_ho_so(status=trang_thai)).tab == R.TAB_AUTO


def test_yeu_cau_bo_sung_thi_chua_du_dieu_kien_status_not_in_pool():
    dong = _dong(_ho_so(status="revision_requested"))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, (R.STATUS_NOT_IN_POOL,))


@pytest.mark.parametrize("trang_thai", R.NO_ROW_STATUSES)
def test_nhap_tu_choi_dang_rut_da_rut_khong_co_dong(trang_thai):
    assert _chay(_ho_so(status=trang_thai)).rows == ()


@pytest.mark.parametrize("trang_thai", qos.OCCUPYING_STATUSES)
def test_da_phe_duyet_kieu_cu_khong_quyet_dinh_thi_legacy_approved_without_decision(trang_thai):
    dong = _dong(_ho_so(status=trang_thai))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, (R.LEGACY_APPROVED_WITHOUT_DECISION,))


def test_da_phe_duyet_kieu_cu_co_quyet_dinh_hieu_luc_thi_da_co_quyet_dinh():
    dong = _dong(_ho_so(status="approved", qd_hieu_luc_id=77))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, ("da_co_quyet_dinh",))


@pytest.mark.parametrize("trang_thai", R.LEGACY_ENGINE_STATUSES)
def test_luong_nguyen_vong_cu_thi_legacy_engine_state(trang_thai):
    dong = _dong(_ho_so(status=trang_thai))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, (R.LEGACY_ENGINE_STATE,))


def test_bon_nhom_trang_thai_roi_nhau_va_phu_du_trang_thai_cua_app():
    nhom = (
        set(R.POOL_STATUSES),
        {R.REVISION_REQUESTED_STATUS},
        set(R.LEGACY_APPROVED_STATUSES),
        set(R.LEGACY_ENGINE_STATUSES),
        set(R.NO_ROW_STATUSES),
    )
    hop = set().union(*nhom)
    assert sum(len(t) for t in nhom) == len(hop)
    assert hop == {s.value for s in AdmissionStatus}


def test_trang_thai_la_thi_loi_du_kien_khong_doan():
    with pytest.raises(R.ReviewInputError):
        _chay(_ho_so(status="trang_thai_moi"))


# ═══════════════════════════════════════════ E2 — học phí HK1 theo chế độ cổng (BT03, BT04) ═══════════════════════════
_MA_TRAN_HOC_PHI = [
    # (chế độ, trạng thái, đã đóng, đạt?)
    (fg.FEE_GATE_MODE_LEGACY, "paid", D("5000000"), True),
    (fg.FEE_GATE_MODE_LEGACY, "waived", D("0"), True),
    (fg.FEE_GATE_MODE_LEGACY, "partial", D("100000"), False),
    (fg.FEE_GATE_MODE_LEGACY, "pending", D("0"), False),
    (fg.FEE_GATE_MODE_LEGACY, "cancelled", D("0"), False),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "paid", D("5000000"), True),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "waived", D("0"), True),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "partial", D("100000"), True),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "partial", D("0"), False),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "overdue", D("100000"), False),
    (fg.FEE_GATE_MODE_SEMESTER_HK1, "pending", D("0"), False),
]


async def _cong_nhap_hoc_dat(che_do, trang_thai, da_dong):
    from app.services.admission_service import check_enrollment_fee_eligibility

    khoan = SimpleNamespace(
        id=1, status=trang_thai, paid_amount=da_dong, remaining_amount=D("5000000") - da_dong, fee_type="tuition"
    )
    kho = MagicMock()
    kho.get_by_profile_id = AsyncMock(return_value=[khoan])
    with patch("app.repositories.fee_repository.FeeRepository", return_value=kho), patch(
        "app.config.settings"
    ) as gia:
        gia.ADMISSION_FEE_GATE_MODE = che_do
        try:
            await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)
        except BadRequest:
            return False
    return True


@pytest.mark.parametrize("che_do,trang_thai,da_dong,dat", _MA_TRAN_HOC_PHI)
async def test_ma_tran_hoc_phi_cung_ket_qua_o_cong_nhap_hoc_va_lan_xet(che_do, trang_thai, da_dong, dat):
    lan_xet = R.TUITION_NOT_CLEARED not in _dong(
        _ho_so(tuition=R.FeeFacts(9001, trang_thai, da_dong)), run=_run(fee_gate_mode=che_do)
    ).reason_codes
    nhap_hoc = await _cong_nhap_hoc_dat(che_do, trang_thai, da_dong)
    assert (fg.evaluate_selected_fee(che_do, status=trang_thai, paid_amount=da_dong).cleared, lan_xet, nhap_hoc) == (
        dat,
        dat,
        dat,
    )


def test_semester_hk1_dong_mot_phan_co_tien_thi_lan_xet_cho_qua():
    dong = _dong(
        _ho_so(tuition=R.FeeFacts(9001, "partial", D("1"))), run=_run(fee_gate_mode=fg.FEE_GATE_MODE_SEMESTER_HK1)
    )
    assert dong.tab == R.TAB_AUTO


def test_legacy_dong_mot_phan_thi_tuition_not_cleared():
    dong = _dong(_ho_so(tuition=R.FeeFacts(9001, "partial", D("4999999"))))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, (R.TUITION_NOT_CLEARED,))


@pytest.mark.parametrize("che_do", ["", "Legacy", " legacy", "semester_HK1", "full", None, 1])
def test_che_do_la_thi_ca_run_bi_tu_choi(che_do):
    with pytest.raises(fg.FeeGateModeInvalid):
        _chay(_ho_so(), run=_run(fee_gate_mode=che_do))


def test_che_do_la_khong_roi_ve_legacy_ke_ca_khoan_da_dong_du():
    with pytest.raises(fg.FeeGateModeInvalid):
        fg.evaluate_selected_fee("semester", status="paid", paid_amount=D("5000000"))


def test_che_do_hop_le_dung_hai_gia_tri_cua_cau_hinh():
    import typing

    from app.config import Settings

    assert set(typing.get_args(Settings.model_fields["ADMISSION_FEE_GATE_MODE"].annotation)) == set(fg.FEE_GATE_MODES)


async def test_cong_nhap_hoc_che_do_la_thi_503_khong_doc_khoan():
    from app.services.admission_service import check_enrollment_fee_eligibility

    kho = MagicMock()
    kho.get_by_profile_id = AsyncMock(return_value=[])
    with patch("app.repositories.fee_repository.FeeRepository", return_value=kho), patch(
        "app.config.settings"
    ) as gia:
        gia.ADMISSION_FEE_GATE_MODE = "semester"
        with pytest.raises(ServiceUnavailableError) as loi:
            await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)
    assert loi.value.public_payload == {"reason_code": fg.FEE_GATE_MODE_INVALID}
    kho.get_by_profile_id.assert_not_called()


def test_khong_co_khoan_hoc_phi_thi_ma_e6_thieu_hoc_phi_hk1_khong_phai_tuition_not_cleared():
    dong = _dong(_ho_so(tuition=None))
    assert dong.reason_codes == ("thieu_hoc_phi_hk1",)


def test_k2_phan_danh_gia_khoan_cu_da_dong_duoc_chon_thi_dat():
    """K2: lượt đọc (L3b) chọn khoản HK1 chưa huỷ ``id`` lớn nhất (bỏ khoản mới hơn ĐÃ HUỶ) — phần CHỌN khoản thuộc L3b (ca CSDL).
    Ở đây: khoản được chọn (khoản cũ đã đóng) ⇒ E2 đạt."""
    assert _dong(_ho_so(tuition=R.FeeFacts(9001, "paid", D("5000000")))).tab == R.TAB_AUTO


def test_khoan_hoc_phi_lech_du_kien_e6_thi_loi_du_kien():
    with pytest.raises(R.ReviewInputError):
        _chay(dataclasses.replace(_ho_so(), check=_check(hp_co=False)))


# ═══════════════════════════════════════════ E3 — lệ phí theo hồ sơ (BT05) ═══════════════════════════════════════════
@pytest.mark.parametrize("trang_thai", ["paid", "waived"])
def test_le_phi_da_dong_hoac_mien_thi_dat(trang_thai):
    assert R.application_fee_cleared([R.FeeFacts(1, trang_thai)], [False])


def test_le_phi_dong_mot_phan_thi_chua_dat_ke_ca_moi_nv_khong_thu():
    assert not R.application_fee_cleared([R.FeeFacts(1, "partial", D("1"))], [True])


def test_moi_nv_khong_thu_le_phi_thi_dat():
    assert R.application_fee_cleared([], [True, True])


def test_nv1_khong_thu_nv2_co_thu_chua_dong_thi_chua_dat():
    assert not R.application_fee_cleared([R.FeeFacts(1, "pending")], [True, False])


def test_hai_khoan_le_phi_thi_chua_dat():
    assert not R.application_fee_cleared([R.FeeFacts(1, "paid"), R.FeeFacts(2, "paid")], [True])


def test_khong_nguyen_vong_nao_thi_khong_chung_minh_duoc_khong_thu():
    assert not R.application_fee_cleared([], [])


def test_le_phi_chua_dat_thi_dong_application_fee_not_cleared():
    dong = _dong(_ho_so(app_fees=(R.FeeFacts(8001, "partial", D("1")),)))
    assert dong.reason_codes == (R.APPLICATION_FEE_NOT_CLEARED,)


# ═══════════════════════════════════════════ E4 — cấu hình giấy (BT06a–g; HĐ15) ═══════════════════════════════════════
@pytest.mark.parametrize(
    "quy_tac",
    [
        {"mandatory_docs": [], "doc_configs": {CU_TRU: {"is_mandatory": False}}},
        {"mandatory_docs": [], "doc_configs": {}},
    ],
    ids=["chi_giay_khong_bat_buoc", "doc_configs_rong"],
)
def test_bt06a_hai_tap_cung_rong_hop_le_thi_e4_dat(quy_tac):
    dong = _dong(_ho_so(applied_rules=quy_tac, docs={}))
    assert (dong.tab, dong.document_gaps) == (R.TAB_AUTO, None)


@pytest.mark.parametrize("khoa", ["mandatory_docs", "doc_configs"])
def test_bt06b_thieu_khoa_thi_document_config_missing(khoa):
    quy_tac = _quy_tac()
    del quy_tac[khoa]
    dong = _dong(_ho_so(applied_rules=quy_tac))
    assert (dong.reason_codes, dong.document_gaps) == ((DOCUMENT_CONFIG_MISSING,), None)


@pytest.mark.parametrize("anh_chup", [None, [], "mandatory_docs", 1])
def test_anh_chup_khong_phai_object_thi_document_config_missing(anh_chup):
    assert required_document_codes(anh_chup).error == DOCUMENT_CONFIG_MISSING


def test_bt06c_giay_bat_buoc_chua_co_dong_thi_mandatory_document_missing():
    dong = _dong(_ho_so(docs={}))
    assert (dong.reason_codes, dong.document_gaps) == (
        (R.MANDATORY_DOCUMENT_MISSING,),
        {"missing": [HOC_BA], "not_verified": []},
    )


@pytest.mark.parametrize(
    "doc_configs",
    [{}, {HOC_BA: {"is_mandatory": False}}],
    ids=["vang_trong_doc_configs", "doc_configs_ghi_khong_bat_buoc"],
)
def test_bt06d_ma_bat_buoc_khong_bat_buoc_trong_doc_configs_thi_invalid(doc_configs):
    quy_tac = {"mandatory_docs": [HOC_BA], "doc_configs": doc_configs}
    assert required_document_codes(quy_tac).error == DOCUMENT_CONFIG_INVALID


def test_bt06f_chieu_nguoc_doc_configs_bat_buoc_ma_mandatory_docs_rong_thi_invalid_khong_mandatory_document():
    quy_tac = {"mandatory_docs": [], "doc_configs": {KHAI_SINH: {"is_mandatory": True}}}
    dong = _dong(_ho_so(applied_rules=quy_tac, docs={}))
    assert (dong.tab, dong.reason_codes, dong.document_gaps) == (R.TAB_INELIGIBLE, (DOCUMENT_CONFIG_INVALID,), None)


def test_bt06f_bien_the_mot_ma_trong_m_hai_ma_trong_d_thi_invalid():
    quy_tac = {"mandatory_docs": ["a"], "doc_configs": {"a": {"is_mandatory": True}, "b": {"is_mandatory": True}}}
    assert required_document_codes(quy_tac).error == DOCUMENT_CONFIG_INVALID


@pytest.mark.parametrize("gia_tri", ["true", "false", None, 0, 1, "<thieu>"])
def test_bt06g_is_mandatory_khong_phai_boolean_json_thi_invalid(gia_tri):
    muc = {} if gia_tri == "<thieu>" else {"is_mandatory": gia_tri}
    quy_tac = {"mandatory_docs": [], "doc_configs": {CU_TRU: muc}}
    assert required_document_codes(quy_tac).error == DOCUMENT_CONFIG_INVALID


@pytest.mark.parametrize(
    "quy_tac",
    [
        {"mandatory_docs": [HOC_BA, HOC_BA], "doc_configs": {HOC_BA: {"is_mandatory": True}}},
        {"mandatory_docs": "hoc_ba_thpt", "doc_configs": {HOC_BA: {"is_mandatory": True}}},
        {"mandatory_docs": [""], "doc_configs": {"": {"is_mandatory": True}}},
        {"mandatory_docs": [1], "doc_configs": {}},
        {"mandatory_docs": None, "doc_configs": {}},
        {"mandatory_docs": [], "doc_configs": []},
        {"mandatory_docs": [], "doc_configs": None},
        {"mandatory_docs": [], "doc_configs": {CU_TRU: "khong_phai_object"}},
    ],
    ids=["ma_trung", "khong_phai_danh_sach", "chuoi_rong", "khong_phai_chuoi", "null", "doc_configs_list", "doc_configs_null",
         "muc_khong_phai_object"],
)
def test_cau_hinh_sai_kieu_thi_invalid(quy_tac):
    assert required_document_codes(quy_tac).error == DOCUMENT_CONFIG_INVALID


def test_cau_hinh_hop_le_tra_dung_tap_ma_bat_buoc_da_sap():
    quy_tac = _quy_tac(mandatory=("so_yeu_ly_lich", HOC_BA))
    assert required_document_codes(quy_tac).codes == (HOC_BA, "so_yeu_ly_lich")


@pytest.mark.parametrize("trang_thai", ["paper_submitted", "rejected", "uploaded", "missing"])
def test_bt06e_giay_bat_buoc_co_dong_chua_duyet_thi_not_verified(trang_thai):
    dong = _dong(_ho_so(docs={HOC_BA: _giay(status=trang_thai)}))
    assert (dong.reason_codes, dong.document_gaps) == (
        (R.MANDATORY_DOCUMENT_NOT_VERIFIED,),
        {"missing": [], "not_verified": [HOC_BA]},
    )


def test_bt06e_giay_khong_bat_buoc_va_giay_ngoai_cau_hinh_khong_chan():
    docs = {HOC_BA: _giay(), CU_TRU: _giay(2, status="rejected"), "giay_ngoai": _giay(3, status="paper_submitted")}
    assert _dong(_ho_so(docs=docs)).tab == R.TAB_AUTO


# ═══════════════════════════════════════════ E5 / E6 / E7 (BT07–BT10) ═══════════════════════════════════════════
def test_bt07_thieu_cccd_thi_thieu_ma_ho_so():
    assert _dong(_ho_so(thieu_ma_ho_so=True)).reason_codes == ("thieu_ma_ho_so",)


def test_bt08_che_do_lan_xet_khong_sinh_nv_in_khac_nv1():
    k = _check(nv1_id=500, nv_in_id=501, nv_in_nganh_id=5, nv_in_path_id=88, nv_in_sg_id=3)
    assert "nv_in_khac_nv1" not in cong.row_block_reason(k, mode=cong.GATE_MODE_REVIEW)


def test_bt08_che_do_lan_xet_khong_sinh_hoc_phi_khac_nganh_nv():
    k = _check(nv1_id=501, nv_in_id=501, nv_in_nganh_id=6, nv_in_path_id=88, nv_in_sg_id=3)
    assert "hoc_phi_khac_nganh_nv" not in cong.row_block_reason(k, mode=cong.GATE_MODE_REVIEW)


def test_bt08_che_do_gd1_mac_dinh_van_sinh_ma_ban_in():
    k = _check(nv1_id=500, nv_in_id=501, nv_in_nganh_id=6, nv_in_path_id=88, nv_in_sg_id=3)
    assert {"nv_in_khac_nv1", "hoc_phi_khac_nganh_nv"} <= set(cong.row_block_reason(k))


def test_bt08_che_do_la_thi_loi():
    with pytest.raises(ValueError):
        cong.row_block_reason(_check(), mode="xet")


def test_bt08_lech_nganh_hoc_phi_thi_tuition_major_mismatch_giu_cho_tam():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, major_id=6)]))
    assert (dong.tab, dong.reason_codes, dong.within_seats) == (
        R.TAB_NEEDS_DECISION,
        (R.TUITION_MAJOR_MISMATCH,),
        True,
    )


def test_e6_muc_ho_so_thi_chua_du_dieu_kien_khong_xet_nv():
    dong = _dong(_ho_so(kv_ly_do="thieu_khu_vuc", kv_muc=None))
    assert (dong.reason_codes, dong.per_choice) == (("thieu_khu_vuc",), ())


def test_e6_muc_nv_luat_kv_khong_xac_dinh_thi_dung_o_nv_ay():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, area_rule=None), _nv(502, 2, HV2)]))
    assert [(o.status, o.reason_codes) for o in dong.per_choice] == [
        (R.CHOICE_CONFIG_MISSING, ("khong_xac_dinh_luat_cong_diem_kv",)),
        (R.CHOICE_NOT_REACHED, ()),
    ]


def test_e6_muc_nv_hai_bang_diem_khac_thi_dung():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, score_both_differ=1)]))
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, ("diem_hai_nguon_khac",))


def test_bt09_co_quyet_dinh_hieu_luc_thi_chan():
    assert _dong(_ho_so(qd_hieu_luc_id=9)).reason_codes == ("da_co_quyet_dinh",)


def test_bt09_cho_admin_quyet_thi_chan():
    assert _dong(_ho_so(cho_quyet_id=9)).reason_codes == ("cho_admin_quyet",)


def test_bt09_dau_appsheet_khong_chan_chi_la_co():
    dong = _dong(_ho_so(dau_appsheet=True))
    assert (dong.tab, dong.flags) == (R.TAB_AUTO, (R.FLAG_APPSHEET_MARK,))


def test_dau_appsheet_o_ho_so_yeu_cau_bo_sung_van_mang_co():
    dong = _dong(_ho_so(status="revision_requested", dau_appsheet=True))
    assert R.FLAG_APPSHEET_MARK in dong.flags


def test_bt10_truot_ba_dieu_kien_ghi_du_ba_ma():
    dong = _dong(_ho_so(tuition=R.FeeFacts(9001, "pending", D("0")), docs={}, thieu_ma_ho_so=True))
    assert dong.reason_codes == tuple(sorted((R.TUITION_NOT_CLEARED, R.MANDATORY_DOCUMENT_MISSING, "thieu_ma_ho_so")))


def test_ngoai_tap_xet_van_ghi_du_ma_e2_e7():
    dong = _dong(_ho_so(status="revision_requested", docs={}))
    assert dong.reason_codes == (R.MANDATORY_DOCUMENT_MISSING, R.STATUS_NOT_IN_POOL)


# ═══════════════════════════════════════════ cổng nguyện vọng (BT11, BT11b) ═══════════════════════════════════════════
def _ket_qua_diem(status, codes, passed):
    return AdmissionScoreResult(
        status=status, passed=passed, final_score=D("12") if status == ProfileStatus.VALID else None,
        selected_subjects=[], subject_scores={}, disqualification_codes=list(codes),
    )


@pytest.fixture
def cong_gia(monkeypatch):
    """Thay ``evaluate_choice_gates`` (đã có test riêng ở engine) để kiểm CÁCH lần xét đọc kết quả cổng."""
    hop = {}

    def _gia(profile, choice):
        if "loi" in hop:
            raise hop["loi"]
        return hop["kq"]

    monkeypatch.setattr(R, "evaluate_choice_gates", _gia)
    monkeypatch.setattr(R, "choice_scoring_config_complete", lambda choice: hop.get("du_cau_hinh", True))
    return hop


_NV_ORM = SimpleNamespace(admission_path=SimpleNamespace(id=88))


def test_bt11_duoi_diem_chuan_ma_hop_le_thi_cong_dat(cong_gia):
    cong_gia["kq"] = ChoiceGateOutcome((), _ket_qua_diem(ProfileStatus.VALID, ["BELOW_MIN_SCORE"], False), True, True)
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM) == R.ChoiceGateFacts(R.GATE_PASSED, ())


def test_bt11_diem_liet_thi_cong_truot_dung_ma_engine(cong_gia):
    cong_gia["kq"] = ChoiceGateOutcome((), _ket_qua_diem(ProfileStatus.INVALID, ["SUBJECT_BELOW_THRESHOLD"], False), True, True)
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM) == R.ChoiceGateFacts(R.GATE_FAILED, ("SUBJECT_BELOW_THRESHOLD",))


def test_bt11b_duoi_diem_tb_toi_thieu_thi_cong_truot(cong_gia):
    cong_gia["kq"] = ChoiceGateOutcome(("BELOW_MIN_GPA",), None, False, False)
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM) == R.ChoiceGateFacts(R.GATE_FAILED, ("BELOW_MIN_GPA",))


def test_khong_co_diem_mon_thi_no_valid_scores(cong_gia):
    cong_gia["kq"] = ChoiceGateOutcome((), None, False, True)
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM) == R.ChoiceGateFacts(R.GATE_FAILED, ("NO_VALID_SCORES",))


def test_thieu_tieu_chi_hoac_to_hop_thi_choice_config_incomplete_truoc_cong(cong_gia):
    cong_gia["du_cau_hinh"] = False
    cong_gia["loi"] = AssertionError("không được gọi cổng khi thiếu cấu hình")
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM).status == R.GATE_CONFIG_INCOMPLETE


def test_thieu_cau_hinh_trinh_do_thi_target_level_not_configured(cong_gia):
    cong_gia["loi"] = ChoiceTargetLevelNotConfigured(display_order=1, gap_kind="degree_level_missing")
    assert R.choice_gate_facts(SimpleNamespace(), _NV_ORM).status == R.GATE_TARGET_LEVEL_NOT_CONFIGURED


def test_bt11b_nv1_truot_cong_thi_xet_nv2():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, gate=R.GATE_FAILED, gate_codes=("BELOW_MIN_GPA",)), _nv(502, 2, HV2)]))
    assert (dong.per_choice[0].status, dong.considered.choice_id) == (R.CHOICE_FAILED_GATE, 502)


@pytest.mark.parametrize(
    "trang_thai_cong,ma",
    [(R.GATE_CONFIG_INCOMPLETE, R.CHOICE_CONFIG_INCOMPLETE), (R.GATE_TARGET_LEVEL_NOT_CONFIGURED, R.TARGET_LEVEL_NOT_CONFIGURED)],
)
def test_cau_hinh_nv_thieu_thi_dung_chua_du_dieu_kien(trang_thai_cong, ma):
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, gate=trang_thai_cong), _nv(502, 2, HV2)]))
    assert (dong.tab, dong.reason_codes, dong.per_choice[1].status) == (R.TAB_INELIGIBLE, (ma,), R.CHOICE_NOT_REACHED)


# ═══════════════════════════════════════════ điểm (BT12, BT13) ═══════════════════════════════════════════
def test_bt12_diem_so_san_bang_diem_in_tran_275():
    dong = _dong(_dtts(kv_muc="2.00"))
    in_ = compute_printed_scores("15.00", "2.00", "2.00")
    assert (dong.scores.priority_total, dong.scores.review_total) == (D("2.75"), D("%.2f" % in_.admission_total))


def test_bt13_bang_san_la_dat():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, subject_total=D("14.25"))]))
    assert (dong.scores.review_total, dong.tab) == (D("15.00"), R.TAB_AUTO)


def test_duoi_san_mot_phan_tram_thi_below_floor():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, subject_total=D("14.24"))]))
    assert (dong.tab, dong.per_choice[0].status) == (R.TAB_NOT_PASSED, R.CHOICE_BELOW_FLOOR)


def test_duong_xet_tat_cong_kv_thi_diem_kv_bang_0():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, area_rule=cong.AREA_RULE_OFF, subject_total=D("16"))]))
    assert dong.scores.area == D("0.00")


def test_duong_xet_tat_cong_doi_tuong_thi_diem_doi_tuong_bang_0():
    dong = _dong(_dtts(nvs=[_nv(501, 1, HV1, object_rule=cong.AREA_RULE_NONE)]))
    assert dong.scores.object == D("0.00")


# ═══════════════════════════════════════════ ưu tiên dân tộc v2 (BT14, BT14a, BT14b, BT15) ═══════════════════════════
def _ut(**kw):
    goc = dict(
        ethnicity_name="Tày",
        birth_certificate=_giay(2),
        permanent_commune_code="01234",
        commune_area_code="KV1",
        residence_proof=_giay(3),
    )
    goc.update(kw)
    return R.ethnic_priority(**goc)


@pytest.mark.parametrize("ten", ["Kinh", "", None])
def test_bt14_buoc_0_kinh_hoac_trong_thi_not_applicable(ten):
    assert _ut(ethnicity_name=ten, birth_certificate=None).state == R.ETHNIC_NOT_APPLICABLE


@pytest.mark.parametrize("khai_sinh", [None, _giay(2, status="paper_submitted"), _giay(2, status="rejected")])
def test_bt14_buoc_1_khai_sinh_chua_duyet_thi_undetermined_h1_a(khai_sinh):
    assert _ut(birth_certificate=khai_sinh) == R.EthnicDecision(R.ETHNIC_UNDETERMINED)


@pytest.mark.parametrize("ma_xa,kv", [("", "KV1"), (None, "KV1"), ("   ", "KV1"), ("01234", None)])
def test_bt14_buoc_2_khong_ma_xa_hoac_khong_tra_ra_kv_thi_undetermined(ma_xa, kv):
    assert _ut(permanent_commune_code=ma_xa, commune_area_code=kv) == R.EthnicDecision(R.ETHNIC_UNDETERMINED)


def test_bt14_buoc_3_giay_cu_tru_bi_tu_choi_thi_undetermined():
    assert _ut(residence_proof=_giay(3, status="rejected")) == R.EthnicDecision(R.ETHNIC_UNDETERMINED)


@pytest.mark.parametrize("kv,ma", [("KV1", "01"), ("KV2", "06"), ("KV2-NT", "06"), ("KV3", "06")])
def test_bt14_buoc_4_giay_cu_tru_da_duyet_thi_full_evidence(kv, ma):
    assert _ut(commune_area_code=kv) == R.EthnicDecision(R.ETHNIC_FULL_EVIDENCE, ma)


@pytest.mark.parametrize("cu_tru", [None, _giay(3, status="uploaded"), _giay(3, status="paper_submitted")])
def test_bt14_buoc_5_giay_cu_tru_chua_co_hoac_dang_cho_thi_tam_cong_va_co(cu_tru):
    assert _ut(residence_proof=cu_tru) == R.EthnicDecision(R.ETHNIC_PROVISIONAL_BY_COMMUNE, "01", residence_proof_missing=True)


def test_bt14_tam_cong_theo_ma_xa_co_cong_diem_va_co_residence_proof_missing():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2)}
    dong = _dong(_dtts(docs=docs))
    assert (dong.scores.object, dong.flags) == (D("2.00"), (R.FLAG_RESIDENCE_PROOF_MISSING,))


def test_bt14_undetermined_khong_tu_cong_phan_dan_toc():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2), CU_TRU: _giay(3, status="rejected")}
    dong = _dong(_dtts(docs=docs))
    assert dong.scores.object == D("0.00")


def test_bt14_undetermined_dat_san_khi_khong_cong_thi_can_ban_thu_ky_quyet_kem_goi_y():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2), CU_TRU: _giay(3, status="rejected")}
    dong = _dong(_dtts(docs=docs))
    assert (dong.tab, dong.reason_codes, dong.decision_hints, dong.within_seats) == (
        R.TAB_NEEDS_DECISION,
        (R.ETHNIC_PRIORITY_UNDETERMINED,),
        (R.HINT_ADMIT_WITHOUT_ETHNIC_BONUS, R.HINT_DEFER_SUPPLEMENT),
        True,
    )


def test_bt14_undetermined_truot_moi_nv_khi_khong_cong_thi_chua_dat_kem_co():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2), CU_TRU: _giay(3, status="rejected")}
    dong = _dong(_dtts(docs=docs, nvs=[_nv(501, 1, HV1, subject_total=D("13.00"))]))
    assert (dong.tab, dong.flags) == (R.TAB_NOT_PASSED, (R.FLAG_ETHNIC_PRIORITY_UNDETERMINED,))


def test_bt14a_khai_sinh_bat_buoc_chua_duyet_thi_chua_du_dieu_kien_khong_tinh_uu_tien():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2, status="paper_submitted")}
    dong = _dong(_dtts(docs=docs, applied_rules=_quy_tac(mandatory=(HOC_BA, KHAI_SINH))))
    assert (dong.reason_codes, dong.ethnic_priority_state, dong.scores, dong.per_choice) == (
        (R.MANDATORY_DOCUMENT_NOT_VERIFIED,),
        None,
        None,
        (),
    )


def test_bt14b_khai_sinh_khong_bat_buoc_chua_duyet_thi_undetermined_khong_phan_dan_toc():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2, status="paper_submitted")}
    dong = _dong(_dtts(docs=docs))
    assert (dong.ethnic_priority_state, dong.scores.object, dong.reason_codes) == (
        R.ETHNIC_UNDETERMINED,
        D("0.00"),
        (R.ETHNIC_PRIORITY_UNDETERMINED,),
    )


def test_bt15_nhieu_dien_lay_muc_cao_nhat_khong_cong_don():
    quyet = R.EthnicDecision(R.ETHNIC_FULL_EVIDENCE, "06")
    rates = {"06": D("1.00"), "03": D("1.00"), "04": D("1.50")}
    assert R.object_score_text(quyet, ["03", "04"], rates, academic_year=NAM) == "1.50"


def test_bt15_ma_01_06_khai_o_dien_khac_khong_tinh_lan_hai():
    assert R.object_score_text(R.EthnicDecision(R.ETHNIC_UNDETERMINED), ["01", "06"], {"01": D("2.00")}, academic_year=NAM) == "0"


def test_bt15_undetermined_van_cong_dien_khac_da_duyet():
    docs = {HOC_BA: _giay(), KHAI_SINH: _giay(2), CU_TRU: _giay(3, status="rejected")}
    assert _dong(_dtts(docs=docs, object_codes=("04",))).scores.object == D("1.50")


def test_thieu_muc_doi_tuong_dang_mo_khi_can_thi_503():
    with pytest.raises(PriorityRateNotConfigured):
        _chay(_dtts(), run=_run(object_rates={}))


def test_thieu_muc_doi_tuong_khi_khong_can_thi_khong_loi():
    dong = _dong(_dtts(nvs=[_nv(501, 1, HV1, object_rule=cong.AREA_RULE_OFF)]), run=_run(object_rates={}))
    assert dong.tab == R.TAB_AUTO


# ═══════════════════════════════════════════ nguyện vọng theo display_order (BT16, BT17, O1) ═══════════════════════════
def test_bt16_nv1_duoi_san_thi_xep_nv2_nv3_khong_xet():
    dong = _dong(
        _ho_so(nvs=[_nv(501, 1, HV1, subject_total=D("10")), _nv(502, 2, HV2), _nv(503, 3, HV3)])
    )
    assert [o.status for o in dong.per_choice] == [R.CHOICE_BELOW_FLOOR, R.CHOICE_PASSED_FLOOR, R.CHOICE_NOT_CONSIDERED]


def test_nv_xet_theo_display_order_khong_theo_thu_tu_dau_vao():
    dong = _dong(_ho_so(nvs=[_nv(502, 2, HV2), _nv(501, 1, HV1)]))
    assert dong.considered.choice_id == 501


@pytest.mark.parametrize(
    "hv,san,ma",
    [
        ({HV1: _hv(HV1, is_deleted=True)}, None, R.ACADEMIC_INFO_DELETED),
        ({HV1: _hv(HV1, annual_quota=None)}, None, R.QUOTA_NOT_CONFIGURED),
        ({HV1: _hv(HV1, group_id=None)}, None, R.GROUP_MISSING),
        ({}, {HV2: D("15.00")}, R.FLOOR_MISSING),
    ],
    ids=["da_xoa", "chi_tieu_trong", "khong_nhom", "thieu_san"],
)
def test_bt17_hoc_vu_khong_xet_duoc_thi_dung_khong_sang_nv_ke(hv, san, ma):
    tat_ca = {HV1: _hv(HV1), HV2: _hv(HV2), HV3: _hv(HV3)}
    tat_ca.update(hv)
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1), _nv(502, 2, HV2)]), run=_run(hv=tat_ca, floors=san))
    assert (dong.tab, dong.reason_codes, [o.status for o in dong.per_choice]) == (
        R.TAB_INELIGIBLE,
        (ma,),
        [R.CHOICE_CONFIG_MISSING, R.CHOICE_NOT_REACHED],
    )


@pytest.mark.parametrize("thieu", ["path_id", "ai"])
def test_phu_luc_2_nv_dut_chuoi_truoc_hoc_vu_thi_choice_config_incomplete_ngay(thieu):
    nv1 = _nv(501, 1, None) if thieu == "ai" else _nv(501, 1, HV1, path_id=None)
    dong = _dong(_ho_so(nvs=[nv1, _nv(502, 2, HV2)]))
    assert (dong.reason_codes, dong.per_choice[0].status) == ((R.CHOICE_CONFIG_INCOMPLETE,), R.CHOICE_CONFIG_MISSING)


def test_bt41_hoc_vu_dang_ngung_van_xet_va_gan_co():
    hv = {HV1: _hv(HV1, offering_inactive=True, major_inactive=True), HV2: _hv(HV2), HV3: _hv(HV3)}
    dong = _dong(_ho_so(), run=_run(hv=hv))
    assert (dong.tab, dong.flags) == (R.TAB_AUTO, (R.FLAG_MAJOR_INACTIVE, R.FLAG_OFFERING_INACTIVE))


# ═══════════════════════════════════════════ chỉ tiêu 0 / trống (BT22a–c, N15, N16) ═══════════════════════════════════
def _hv_dong():
    """Học vụ 41 chỉ tiêu 0 (đóng tuyệt đối); 57, 63 chỉ tiêu 10."""
    return {HV1: _hv(HV1, annual_quota=0), HV2: _hv(HV2), HV3: _hv(HV3)}


def test_bt22a_o1_chi_tieu_0_thi_xet_tiep_nv_ke_va_gan_co():
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1), _nv(502, 2, HV2)]), run=_run(hv=_hv_dong()))
    assert (dong.per_choice[0].status, dong.considered.offering_academic_info_id, dong.flags) == (
        R.CHOICE_QUOTA_CLOSED,
        HV2,
        (R.FLAG_QUOTA_CLOSED,),
    )


def test_bt22a_khong_dong_nao_duoc_xep_vao_hoc_vu_chi_tieu_0():
    ho_so = [_ho_so(1000 + i, nvs=[_nv(500 + i, 1, HV1, subject_total=D("20"))]) for i in range(3)]
    rows = _chay(*ho_so, run=_run(hv=_hv_dong())).rows
    assert [r.considered for r in rows] == [None, None, None]


def test_n15_chi_co_nv_vao_nganh_dong_thi_chua_dat_kem_quota_closed():
    dong = _dong(_ho_so(), run=_run(hv=_hv_dong()))
    assert (dong.tab, dong.reason_codes, dong.flags) == (
        R.TAB_NOT_PASSED,
        (R.ALL_CHOICES_FAILED, R.QUOTA_CLOSED),
        (R.FLAG_QUOTA_CLOSED,),
    )


def test_n16_nganh_chi_tieu_0_khong_nhom_khong_san_van_la_dong_tuyen():
    hv = _hv_dong()
    hv[HV1] = _hv(HV1, annual_quota=0, group_id=None)
    dong = _dong(_ho_so(), run=_run(hv=hv, floors={}))
    assert dong.per_choice[0].status == R.CHOICE_QUOTA_CLOSED


def test_bt22b_chi_tieu_trong_khong_phai_khong_gioi_han():
    hv = {HV1: _hv(HV1, annual_quota=None), HV2: _hv(HV2), HV3: _hv(HV3)}
    dong = _dong(_ho_so(nvs=[_nv(501, 1, HV1, subject_total=D("29"))]), run=_run(hv=hv))
    assert (dong.considered, dong.reason_codes) == (None, (R.QUOTA_NOT_CONFIGURED,))


def test_bt22c_chi_tieu_0_sang_nv_ke_con_chi_tieu_trong_thi_dung():
    nvs = [_nv(501, 1, HV1), _nv(502, 2, HV2)]
    dong_0 = _dong(_ho_so(nvs=nvs), run=_run(hv=_hv_dong()))
    hv_trong = {HV1: _hv(HV1, annual_quota=None), HV2: _hv(HV2), HV3: _hv(HV3)}
    dong_trong = _dong(_ho_so(nvs=nvs), run=_run(hv=hv_trong))
    assert (dong_0.tab, dong_trong.tab) == (R.TAB_AUTO, R.TAB_INELIGIBLE)


# ═══════════════════════════════════════════ xếp theo Q1 (BT18–BT21) ═══════════════════════════════════════════
def test_bt18_nv1_nv2_binh_dang_theo_diem():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2), HV3: _hv(HV3)}
    a = _ho_so(1001, nvs=[_nv(511, 1, HV2, subject_total=D("10")), _nv(512, 2, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17"))])
    rows = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv)).rows}
    assert (rows[1001].tab, rows[1002].reason_codes) == (R.TAB_AUTO, (R.OVER_MAJOR_QUOTA,))


@pytest.mark.parametrize("ids", [(1001, 1002), (1002, 1001)])
def test_bt19_bang_diem_o_cho_cuoi_thi_ca_hai_tie_at_last_seat(ids):
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2), HV3: _hv(HV3)}
    a = _ho_so(ids[0], nvs=[_nv(511, 1, HV1, subject_total=D("16"))])
    b = _ho_so(ids[1], nvs=[_nv(522, 2, HV1, subject_total=D("16")), ])
    rows = _chay(a, b, run=_run(hv=hv)).rows
    assert [(r.reason_codes, r.within_seats, r.rank_in_major) for r in rows] == [((R.TIE_AT_LAST_SEAT,), False, 1)] * 2


def test_bt19_bang_diem_khong_phai_cho_cuoi_thi_ca_hai_trong_so_cho():
    assert R.rank_major({1: D("16"), 2: D("16"), 3: D("15")}, 2) == {
        1: R.SeatOutcome(1, True, None),
        2: R.SeatOutcome(1, True, None),
        3: R.SeatOutcome(2, False, R.OVER_MAJOR_QUOTA),
    }


def test_bt19_em_diem_cao_hon_nhom_bang_diem_van_trong_so_cho():
    assert R.rank_major({1: D("18"), 2: D("16"), 3: D("16"), 4: D("15")}, 2) == {
        1: R.SeatOutcome(1, True, None),
        2: R.SeatOutcome(2, False, R.TIE_AT_LAST_SEAT),
        3: R.SeatOutcome(2, False, R.TIE_AT_LAST_SEAT),
        4: R.SeatOutcome(3, False, R.OVER_MAJOR_QUOTA),
    }


def test_het_cho_thi_moi_em_over_major_quota():
    hv = {HV1: _hv(HV1, annual_quota=5, used=7), HV2: _hv(HV2), HV3: _hv(HV3)}
    dong = _dong(_ho_so(), run=_run(hv=hv))
    assert (dong.reason_codes, dong.within_seats) == ((R.OVER_MAJOR_QUOTA,), False)


def test_cho_con_tinh_bang_chi_tieu_tru_da_dung():
    hv = {HV1: _hv(HV1, annual_quota=3, used=2), HV2: _hv(HV2), HV3: _hv(HV3)}
    rows = _chay(*[_ho_so(1000 + i, nvs=[_nv(500 + i, 1, HV1, subject_total=D(15 + i))]) for i in range(2)], run=_run(hv=hv)).rows
    assert [r.tab for r in rows] == [R.TAB_NEEDS_DECISION, R.TAB_AUTO]


def test_bt20_vuot_chi_tieu_khong_tu_chuyen_nv_ke():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2), HV3: _hv(HV3)}
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17")), _nv(522, 2, HV2)])
    dong_b = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv)).rows}[1002]
    assert (dong_b.considered.choice_id, dong_b.per_choice[1].status, dong_b.decision_hints) == (
        521,
        R.CHOICE_NOT_CONSIDERED,
        (R.HINT_ADMIT_OVER_MAJOR_QUOTA, R.HINT_CONSIDER_NEXT_CHOICE),
    )


def test_goi_y_nv_ke_khong_tro_vao_hoc_vu_chi_tieu_0():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2, annual_quota=0), HV3: _hv(HV3)}
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17")), _nv(522, 2, HV2)])
    dong_b = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv)).rows}[1002]
    assert R.HINT_CONSIDER_NEXT_CHOICE not in dong_b.decision_hints


#: Owner 22-11 "MỌI mã dừng của máy xét" (``gd2/gd2b/dot2/QUYET-DINH-OWNER-GD2B-DOT2-MOI-MA-DUNG-2026-11-22.md``; trước đó
#: ``…MA-DUNG-GOI-Y…``, Codex GĐ2-B lượt 2 P3): NV2 mà máy xét DỪNG ⇒ KHÔNG gợi ý ``consider_next_choice`` dù NV3 còn chỉ tiêu — gợi ý
#: và máy xét dừng ở CÙNG chỗ, qua MỘT vị từ ``choice_config_verdict``. (nhãn ca, mã dừng mong đợi của NV2) — bước 0–2 và 4–6.
_MA_DUNG_NV2 = (
    ("thieu_hoc_vu", (R.CHOICE_CONFIG_INCOMPLETE,)),  # bước 0 — đứt chuỗi
    ("thieu_duong_xet", (R.CHOICE_CONFIG_INCOMPLETE,)),  # bước 0 — đứt chuỗi
    ("nam_khac", (R.CHOICE_ACADEMIC_YEAR_MISMATCH,)),  # bước 0
    ("da_xoa", (R.ACADEMIC_INFO_DELETED,)),  # bước 1
    ("chi_tieu_trong", (R.QUOTA_NOT_CONFIGURED,)),  # bước 2
    ("thieu_nhom", (R.GROUP_MISSING,)),  # bước 4
    ("thieu_diem_san", (R.FLOOR_MISSING,)),  # bước 5
    ("thieu_loai_hinh", (R.CHOICE_CONFIG_INCOMPLETE,)),  # bước 6 — học vụ không có loại hình
    ("cong_chua_du_cau_hinh", (R.CHOICE_CONFIG_INCOMPLETE,)),  # bước 6 — cổng ``config_incomplete``
    ("chua_cau_hinh_trinh_do", (R.TARGET_LEVEL_NOT_CONFIGURED,)),  # bước 6
    ("e6_hai_bang_diem_khac", ("diem_hai_nguon_khac",)),  # bước 6 — E6 mức NV
)


def _nv2_theo_ca(ca):
    """(NV2, học vụ HV2, bảng sàn) của một ca trong ``_MA_DUNG_NV2``."""
    nv2, hv2, san = _nv(522, 2, HV2), _hv(HV2), None
    if ca == "thieu_hoc_vu":
        nv2 = _nv(522, 2, None)
    elif ca == "thieu_duong_xet":
        nv2 = _nv(522, 2, HV2, path_id=None)
    elif ca == "nam_khac":
        hv2 = _hv(HV2, academic_year=NAM - 1)
    elif ca == "da_xoa":
        hv2 = _hv(HV2, is_deleted=True)
    elif ca == "chi_tieu_trong":
        hv2 = _hv(HV2, annual_quota=None)
    elif ca == "thieu_nhom":
        hv2 = _hv(HV2, group_id=None)
    elif ca == "thieu_diem_san":
        san = {HV1: D("15.00"), HV3: D("15.00")}
    elif ca == "thieu_loai_hinh":
        hv2 = _hv(HV2, offering_id=None)
    elif ca == "cong_chua_du_cau_hinh":
        nv2 = _nv(522, 2, HV2, gate=R.GATE_CONFIG_INCOMPLETE)
    elif ca == "chua_cau_hinh_trinh_do":
        nv2 = _nv(522, 2, HV2, gate=R.GATE_TARGET_LEVEL_NOT_CONFIGURED)
    elif ca == "e6_hai_bang_diem_khac":
        nv2 = _nv(522, 2, HV2, score_both_differ=1)
    elif ca != "doi_chung":
        raise AssertionError(ca)
    return nv2, hv2, san


def _ba_nv_nv1_vuot_chi_tieu(nv2, hv2, san=None, nv3_hv=None):
    """A chiếm chỗ duy nhất của HV1; B: NV1 HV1 (vượt chỉ tiêu ⇒ cần quyết), NV2 theo ca, NV3 HV3 còn chỉ tiêu (hoặc ``nv3_hv``).
    Trả (dòng của B, phán quyết vị từ chung cho NV2, phán quyết cho NV3)."""
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: hv2, HV3: nv3_hv or _hv(HV3)}
    run = _run(hv=hv, floors=san)
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17")), nv2, _nv(523, 3, HV3)])
    dong_b = {r.profile_id: r for r in _chay(a, b, run=run).rows}[1002]
    return dong_b, R.choice_config_verdict(b.choices[1], run), R.choice_config_verdict(b.choices[2], run)


@pytest.mark.parametrize("ca, ma", _MA_DUNG_NV2, ids=[c[0] for c in _MA_DUNG_NV2])
def test_goi_y_nv_sau_dung_o_nv_mang_ma_dung_du_nv3_con_chi_tieu(ca, ma):
    dong_b, nv2, nv3 = _ba_nv_nv1_vuot_chi_tieu(*_nv2_theo_ca(ca))
    # Ca canh ĐÚNG bước của nó: NV2 dừng với đúng mã, NV3 xét được.
    assert (nv2.kind, nv2.codes) == (R.CHOICE_STEP_STOP, ma), (ca, nv2)
    assert nv3.kind == R.CHOICE_STEP_CONSIDER, (ca, nv3)
    assert (dong_b.tab, dong_b.considered.choice_id) == (R.TAB_NEEDS_DECISION, 521), dong_b
    assert dong_b.decision_hints == (R.HINT_ADMIT_OVER_MAJOR_QUOTA,), (ca, dong_b.decision_hints)


def test_goi_y_nv_sau_chi_di_qua_nv_chi_tieu_0_toi_nv3_con_chi_tieu():
    """Đối chứng: NV2 chỉ tiêu 0 (ngành đã đóng — máy xét sang NV kế) ⇒ đi tiếp ⇒ NV3 còn chỉ tiêu ⇒ CÓ gợi ý."""
    dong_b, nv2, _ = _ba_nv_nv1_vuot_chi_tieu(_nv(522, 2, HV2), _hv(HV2, annual_quota=0))
    assert nv2.kind == R.CHOICE_STEP_NEXT
    assert dong_b.decision_hints == (R.HINT_ADMIT_OVER_MAJOR_QUOTA, R.HINT_CONSIDER_NEXT_CHOICE), dong_b.decision_hints


def test_goi_y_qua_nv_chi_tieu_0_roi_nv_sau_dung_o_buoc_4_thi_khong_goi_y():
    """NV2 chỉ tiêu 0 (đi tiếp) rồi NV3 THIẾU NHÓM ngành (bước 4 — máy xét dừng) ⇒ KHÔNG gợi ý."""
    dong_b, nv2, nv3 = _ba_nv_nv1_vuot_chi_tieu(
        _nv(522, 2, HV2), _hv(HV2, annual_quota=0), nv3_hv=_hv(HV3, group_id=None)
    )
    assert (nv2.kind, nv3.kind, nv3.codes) == (R.CHOICE_STEP_NEXT, R.CHOICE_STEP_STOP, (R.GROUP_MISSING,))
    assert dong_b.decision_hints == (R.HINT_ADMIT_OVER_MAJOR_QUOTA,), dong_b.decision_hints


def test_goi_y_nv_sau_cong_truot_van_la_nv_xet_duoc():
    """Đối chứng bước 7: NV2 cổng ``failed`` (máy xét SANG NV kế, không phải mã dừng) ⇒ NV2 vẫn "xét được" ⇒ CÓ gợi ý."""
    dong_b, nv2, _ = _ba_nv_nv1_vuot_chi_tieu(_nv(522, 2, HV2, gate=R.GATE_FAILED, gate_codes=("x",)), _hv(HV2))
    assert nv2.kind == R.CHOICE_STEP_CONSIDER
    assert R.HINT_CONSIDER_NEXT_CHOICE in dong_b.decision_hints, dong_b.decision_hints


def test_mot_vi_tu_chung_cho_may_xet_va_goi_y(monkeypatch):
    """CLAUDE.md §7 + §10 (đo ở chỗ nối): CẢ máy xét lẫn gợi ý gọi ``choice_config_verdict`` — thay vị từ bằng bản "mọi NV ngoài NV1
    dừng với mã giả" thì máy xét ghi đúng mã giả cho NV1 không, còn gợi ý thì tắt."""
    goc = R.choice_config_verdict

    def gia(choice, run):
        if choice.display_order == 1:
            return goc(choice, run)
        return R.ChoiceConfigVerdict(R.CHOICE_STEP_STOP, ("ma_gia",))

    monkeypatch.setattr(R, "choice_config_verdict", gia)
    dong_b, _, _ = _ba_nv_nv1_vuot_chi_tieu(*_nv2_theo_ca("doi_chung"))
    assert dong_b.decision_hints == (R.HINT_ADMIT_OVER_MAJOR_QUOTA,), dong_b.decision_hints
    # Máy xét: NV1 đi qua vị từ thật; một hồ sơ chỉ có NV2 (thứ tự 1 giả) ⇒ mã giả là kết quả của máy xét.
    monkeypatch.setattr(R, "choice_config_verdict", lambda choice, run: R.ChoiceConfigVerdict(R.CHOICE_STEP_STOP, ("ma_gia",)))
    dong = _dong(_ho_so())
    assert (dong.tab, dong.reason_codes) == (R.TAB_INELIGIBLE, ("ma_gia",)), dong


def test_goi_y_nv_sau_duyet_theo_thu_tu_may_xet_khong_theo_thu_tu_luu():
    """NV lưu theo thứ tự NV1, NV3, NV2; NV2 (thứ tự 2) năm khác ⇒ máy xét dừng ở NV2 ⇒ KHÔNG gợi ý (duyệt theo thứ tự lưu sẽ gặp NV3
    còn chỉ tiêu trước rồi gợi ý sai)."""
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2, academic_year=NAM - 1), HV3: _hv(HV3)}
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17")), _nv(523, 3, HV3), _nv(522, 2, HV2)])
    dong_b = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv)).rows}[1002]
    assert dong_b.decision_hints == (R.HINT_ADMIT_OVER_MAJOR_QUOTA,), dong_b.decision_hints


def test_goi_y_trung_vuot_chi_khi_nhom_con_cho_sau_phan_auto():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2), HV3: _hv(HV3)}
    nhom_het = (R.GroupFacts(NHOM, "N1", "Nhóm 1", ceiling=1),)
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17"))])
    dong_b = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv, groups=nhom_het)).rows}[1002]
    assert R.HINT_ADMIT_OVER_MAJOR_QUOTA not in dong_b.decision_hints


def test_bt21_trong_so_cho_lech_nganh_hoc_phi_van_giu_cho_em_ke_khong_len_auto():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2), HV3: _hv(HV3)}
    a = _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"), major_id=6)])
    b = _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17"))])
    rows = {r.profile_id: r for r in _chay(a, b, run=_run(hv=hv)).rows}
    assert ((rows[1001].tab, rows[1001].within_seats), rows[1002].tab) == (
        (R.TAB_NEEDS_DECISION, True),
        R.TAB_NEEDS_DECISION,
    )


# ═══════════════════════════════════════════ quy ước dòng (L1 CHECK; HĐ16) ═══════════════════════════════════════════
def _run_hon_hop():
    hv = {HV1: _hv(HV1, annual_quota=1), HV2: _hv(HV2, annual_quota=0), HV3: _hv(HV3, annual_quota=None)}
    ho_so = [
        _ho_so(1001, nvs=[_nv(511, 1, HV1, subject_total=D("18"))]),
        _ho_so(1002, nvs=[_nv(521, 1, HV1, subject_total=D("17"))]),
        _ho_so(1003, nvs=[_nv(531, 1, HV2)]),
        _ho_so(1004, nvs=[_nv(541, 1, HV3)]),
        _ho_so(1005, docs={}),
        _ho_so(1006, status="revision_requested"),
        _ho_so(1007, status="enrolled"),
    ]
    return _chay(*ho_so, run=_run(hv=hv))


def test_quy_uoc_per_choice_rong_khi_va_chi_khi_khong_tinh_uu_tien():
    rows = _run_hon_hop().rows
    assert {r.profile_id for r in rows if r.per_choice == ()} == {1005, 1006, 1007}
    for r in rows:
        assert (r.per_choice == ()) == (r.ethnic_priority_state is None), r


def test_quy_uoc_per_choice_rong_thi_chua_du_dieu_kien_va_khong_diem():
    for r in _run_hon_hop().rows:
        if r.per_choice == ():
            assert (r.tab, r.scores) == (R.TAB_INELIGIBLE, None), r


def test_quy_uoc_dung_o_mot_nv_thi_chua_du_dieu_kien_van_co_per_choice_va_uu_tien():
    dong = {r.profile_id: r for r in _run_hon_hop().rows}[1004]
    assert (dong.tab, dong.reason_codes, dong.ethnic_priority_state, len(dong.per_choice)) == (
        R.TAB_INELIGIBLE,
        (R.QUOTA_NOT_CONFIGURED,),
        R.ETHNIC_NOT_APPLICABLE,
        1,
    )


def test_quy_uoc_auto_va_can_quyet_khi_va_chi_khi_co_nv_duoc_xep():
    for r in _run_hon_hop().rows:
        assert (r.tab in (R.TAB_AUTO, R.TAB_NEEDS_DECISION)) == (r.considered is not None), r


def test_quy_uoc_khong_phai_auto_thi_co_ma_ly_do():
    for r in _run_hon_hop().rows:
        assert (r.tab == R.TAB_AUTO) == (r.reason_codes == ()), r


def test_ho_so_khong_co_nv_thi_e6_chan_o_muc_ho_so():
    ho_so = dataclasses.replace(_ho_so(), choices=(), check=_check(so_nv=0, uses_choice_engine=True))
    dong = _dong(ho_so)
    assert dong.reason_codes == ("nhieu_nv_khong_co_nv",)


def test_so_nv_lech_du_kien_e6_thi_loi_du_kien():
    with pytest.raises(R.ReviewInputError):
        _chay(dataclasses.replace(_ho_so(), choices=()))


# ═══════════════════════════════════════════ row_hash (BT26) ═══════════════════════════════════════════
def _bam(ho_so, run=None):
    return _dong(ho_so, run=run).row_hash


def test_row_hash_la_64_hex():
    h = _bam(_ho_so())
    assert len(h) == 64 and set(h) <= set("0123456789abcdef")


def test_bt26_doi_verified_format_thi_doi_bam():
    assert _bam(_ho_so()) != _bam(_ho_so(docs={HOC_BA: _giay(verified_format="ban_chinh")}))


def test_bt26_doi_row_version_thi_doi_bam():
    assert _bam(_ho_so()) != _bam(_ho_so(docs={HOC_BA: _giay(row_version=2)}))


def test_bt26_doi_trang_thai_phi_thi_doi_bam():
    assert _bam(_ho_so()) != _bam(_ho_so(tuition=R.FeeFacts(9001, "waived", D("5000000"))))


def test_bt26_doi_san_thi_doi_bam():
    assert _bam(_ho_so()) != _bam(_ho_so(), run=_run(floors={HV1: D("14.00"), HV2: D("15.00"), HV3: D("15.00")}))


def test_bt26_doi_nhan_nganh_khong_doi_bam():
    hv = {HV1: _hv(HV1, major_name="Tên mới", major_code="X9"), HV2: _hv(HV2), HV3: _hv(HV3)}
    assert _bam(_ho_so()) == _bam(_ho_so(), run=_run(hv=hv))


def test_bt26_doi_nhan_giay_trong_anh_chup_khong_doi_bam():
    quy_tac = _quy_tac()
    quy_tac["doc_configs"][HOC_BA]["label"] = "Học bạ (tên mới)"
    assert _bam(_ho_so()) == _bam(_ho_so(applied_rules=quy_tac))


def test_bt26_chay_lai_cung_du_kien_thi_cung_bam():
    assert _bam(_ho_so()) == _bam(_ho_so())


def test_bt26_dao_thu_tu_khoan_le_phi_dau_vao_thi_cung_bam():
    hai_khoan = (R.FeeFacts(8001, "paid", D("30000")), R.FeeFacts(8002, "pending", D("0")))
    assert _bam(_ho_so(app_fees=hai_khoan)) == _bam(_ho_so(app_fees=tuple(reversed(hai_khoan))))


# ── Codex B3 (đợt 1): băm ổn định theo GIÁ TRỊ, không theo cách viết ─────────────────────────────────────────────────────────
SYLL = "so_yeu_ly_lich"


def test_b3_dao_thu_tu_ma_giay_bat_buoc_thi_cung_bam():
    """E4 coi ``mandatory_docs`` là TẬP ⇒ ``[A, B]`` và ``[B, A]`` (cùng ``doc_configs``) cho CÙNG băm."""
    xuoi = _ho_so(applied_rules=_quy_tac(mandatory=(HOC_BA, SYLL)), docs={HOC_BA: _giay(), SYLL: _giay(doc_id=2)})
    nguoc = _ho_so(applied_rules=_quy_tac(mandatory=(SYLL, HOC_BA)), docs={HOC_BA: _giay(), SYLL: _giay(doc_id=2)})
    assert _bam(xuoi) == _bam(nguoc)


def test_b3_doi_tap_ma_giay_bat_buoc_thi_doi_bam():
    """Giá trị nghiệp vụ đổi (thêm một giấy bắt buộc) ⇒ băm đổi."""
    mot = _ho_so(applied_rules=_quy_tac(mandatory=(HOC_BA,)), docs={HOC_BA: _giay(), SYLL: _giay(doc_id=2)})
    hai = _ho_so(applied_rules=_quy_tac(mandatory=(HOC_BA, SYLL)), docs={HOC_BA: _giay(), SYLL: _giay(doc_id=2)})
    assert _bam(mot) != _bam(hai)


def test_b3_vat_lieu_cau_hinh_giay_sap_ma_va_giu_phan_biet_thieu_voi_hong():
    """Vật liệu băm của ``required_document_codes``: danh sách mã ĐÃ SẮP; cấu hình THIẾU và HỎNG mang trạng thái khác nhau ngay trong
    vật liệu (không chỉ nhờ mã lý do của dòng)."""
    xuoi = required_document_codes(_quy_tac(mandatory=(HOC_BA, SYLL)))
    nguoc = required_document_codes(_quy_tac(mandatory=(SYLL, HOC_BA)))
    assert xuoi.material == nguoc.material and xuoi.material["mandatory_docs"] == sorted([HOC_BA, SYLL])
    thieu = _quy_tac()
    del thieu["mandatory_docs"]
    hong = _quy_tac()
    hong["mandatory_docs"] = HOC_BA  # chuỗi thay cho danh sách
    assert (required_document_codes(thieu).material["state"], required_document_codes(hong).material["state"]) == (
        DOCUMENT_CONFIG_MISSING,
        DOCUMENT_CONFIG_INVALID,
    )


def test_b3_muc_khu_vuc_viet_0_5_hay_0_50_thi_cung_bam():
    """``kv_muc`` là chuỗi số: ``"0.5"`` và ``"0.50"`` là CÙNG điểm khu vực ⇒ cùng băm."""
    assert _bam(_ho_so(kv_muc="0.5")) == _bam(_ho_so(kv_muc="0.50"))


def test_b3_muc_khu_vuc_doi_gia_tri_thi_doi_bam():
    assert _bam(_ho_so(kv_muc="0.5")) != _bam(_ho_so(kv_muc="0.75"))


# ═══════════════════════════════════════════ cờ A13 (K4 + biên bản A13) / A19 ═══════════════════════════════════════════
@pytest.mark.parametrize("trang_thai", qos.OCCUPYING_STATUSES)
def test_a13_cung_cccd_nam_truoc_dang_chiem_cho_thi_bat_co_kem_trang_thai(trang_thai):
    assert R.same_citizen_previous_year(NAM, [R.PriorYearProfileFacts(NAM - 1, trang_thai, False)]) == (
        R.PriorYearFinding(NAM - 1, R.A13_BASIS_OCCUPYING, trang_thai),
    )


def test_a13_quyet_dinh_hieu_luc_ghi_trong_phan_mem_thi_bat_co_du_khong_chiem_cho():
    assert R.same_citizen_previous_year(NAM, [R.PriorYearProfileFacts(NAM - 2, "withdrawn", True)]) == (
        R.PriorYearFinding(NAM - 2, R.A13_BASIS_ADMISSION_DECISION, None),
    )


def test_a13_thu_tu_nam_giam_dan_roi_can_cu():
    ket_qua = R.same_citizen_previous_year(
        NAM,
        [
            R.PriorYearProfileFacts(2023, "enrolled", False),
            R.PriorYearProfileFacts(2025, "approved", True),
            R.PriorYearProfileFacts(2024, "withdrawn", True),
        ],
    )
    assert [(f.year, f.basis) for f in ket_qua] == [
        (2025, R.A13_BASIS_ADMISSION_DECISION),
        (2025, R.A13_BASIS_OCCUPYING),
        (2024, R.A13_BASIS_ADMISSION_DECISION),
        (2023, R.A13_BASIS_OCCUPYING),
    ]


def test_a13_phan_tu_chi_co_nam_can_cu_trang_thai_khong_du_lieu_ca_nhan():
    dong = _dong(_ho_so(prior=[R.PriorYearProfileFacts(2025, "enrolled", True)]))
    assert [sorted(p) for p in dong.column_values()["prior_year_findings"]] == [["basis", "status", "year"]] * 2


@pytest.mark.parametrize("trang_thai", ["submitted", "rejected", "withdrawn", "result_published"])
def test_a13_nam_truoc_khong_chiem_cho_khong_quyet_dinh_thi_khong_co(trang_thai):
    assert R.same_citizen_previous_year(NAM, [R.PriorYearProfileFacts(NAM - 1, trang_thai, False)]) == ()


def test_a13_moi_nam_truoc_khong_chi_nam_lien_truoc():
    assert R.same_citizen_previous_year(NAM, [R.PriorYearProfileFacts(2024, "enrolled", False)])[0].year == 2024


def test_a13_ho_so_nam_khong_nho_hon_y_thi_loi_du_kien():
    with pytest.raises(R.ReviewInputError):
        R.same_citizen_previous_year(NAM, [R.PriorYearProfileFacts(NAM, "enrolled", False)])


def test_a13_bat_co_khong_doi_tab():
    dong = _dong(_ho_so(prior=[R.PriorYearProfileFacts(2024, "enrolled", True)]))
    assert (dong.tab, dong.flags) == (R.TAB_AUTO, (R.FLAG_SAME_CITIZEN_PREVIOUS_YEAR,))


def test_a13_cot_prior_year_findings_dung_dang_phu_luc():
    dong = _dong(_ho_so(prior=[R.PriorYearProfileFacts(2024, "enrolled", True)]))
    assert dong.column_values()["prior_year_findings"] == [
        {"year": 2024, "basis": "admission_decision", "status": None},
        {"year": 2024, "basis": "occupying_status", "status": "enrolled"},
    ]


def test_a13_khong_co_can_cu_thi_mang_rong_va_khong_co():
    dong = _dong(_ho_so(prior=[R.PriorYearProfileFacts(2025, "submitted", False)]))
    assert (dong.column_values()["prior_year_findings"], R.FLAG_SAME_CITIZEN_PREVIOUS_YEAR in dong.flags) == ([], False)


def test_a13_bat_bien_co_khi_va_chi_khi_mang_khac_rong():
    ho_so = [
        _ho_so(1001, prior=[R.PriorYearProfileFacts(2025, "enrolled", False)]),
        _ho_so(1002, prior=[R.PriorYearProfileFacts(2025, "rejected", False)]),
        _ho_so(1003, prior=[R.PriorYearProfileFacts(2024, "withdrawn", True)], docs={}),
        _ho_so(1004, status="revision_requested", prior=[R.PriorYearProfileFacts(2024, "admitted", False)]),
        _ho_so(1005),
    ]
    rows = _chay(*ho_so).rows
    assert [bool(r.prior_year_findings) for r in rows] == [True, False, True, True, False]
    for r in rows:
        assert (R.FLAG_SAME_CITIZEN_PREVIOUS_YEAR in r.flags) == bool(r.column_values()["prior_year_findings"]), r


def test_bt26_doi_can_cu_a13_thi_doi_bam():
    assert _bam(_ho_so()) != _bam(_ho_so(prior=[R.PriorYearProfileFacts(2025, "enrolled", False)]))


def test_a19_dang_auto_o_lan_xet_nhap_khac_thi_co_khong_doi_tab():
    dong = _dong(_ho_so(1001), run=_run(other_draft_auto_profile_ids=frozenset({1001})))
    assert (dong.tab, dong.flags) == (R.TAB_AUTO, (R.FLAG_SELECTED_IN_OTHER_DRAFT_SESSION,))


# ═══════════════════════════════════════════ quota_view + cảnh báo (BT43; §9.4) ═══════════════════════════════════════
def test_bt43_co_hoc_vu_chi_tieu_0_thi_canh_bao_quota_closed_present():
    assert R.WARNING_QUOTA_CLOSED_PRESENT in _chay(_ho_so(), run=_run(hv=_hv_dong())).summary["warnings"]


def test_khong_co_hoc_vu_chi_tieu_0_thi_khong_canh_bao_quota_closed_present():
    assert R.WARNING_QUOTA_CLOSED_PRESENT not in _chay(_ho_so()).summary["warnings"]


def test_hoc_vu_chi_tieu_0_da_xoa_khong_tinh_canh_bao():
    hv = _hv_dong()
    hv[HV1] = _hv(HV1, annual_quota=0, is_deleted=True)
    assert R.WARNING_QUOTA_CLOSED_PRESENT not in _chay(_ho_so(nvs=[_nv(502, 1, HV2)]), run=_run(hv=hv)).summary["warnings"]


def test_bang_chi_tieu_nhap_thi_canh_bao_quota_table_not_locked():
    assert _chay(_ho_so(), run=_run(quota_table_status="draft")).summary["warnings"] == [R.WARNING_QUOTA_TABLE_NOT_LOCKED]


def test_nhom_vuot_tran_sau_phan_auto_chi_canh_bao():
    ket_qua = _chay(_ho_so(), run=_run(groups=(R.GroupFacts(NHOM, "N1", "Nhóm 1", ceiling=1, used=1),)))
    assert (ket_qua.rows[0].tab, ket_qua.summary["warnings"], ket_qua.quota_view["groups"][0]["would_exceed"]) == (
        R.TAB_AUTO,
        [R.WARNING_GROUP_CEILING_WOULD_EXCEED],
        True,
    )


def test_quota_view_trang_thai_va_cho_con_tung_hoc_vu():
    hv = {
        HV1: _hv(HV1, annual_quota=3, used=1),
        HV2: _hv(HV2, annual_quota=0),
        HV3: _hv(HV3, annual_quota=None),
        64: _hv(64, group_id=None),
        65: _hv(65, is_deleted=True),
        66: _hv(66),
    }
    majors = {m["offering_academic_info_id"]: m for m in _chay(_ho_so(), run=_run(hv=hv)).quota_view["majors"]}
    assert {k: (m["state"], m["remaining"], m["auto"]) for k, m in majors.items()} == {
        HV1: (R.QUOTA_STATE_OK, 2, 1),
        HV2: (R.QUOTA_STATE_CLOSED, 0, 0),
        HV3: (R.QUOTA_STATE_NOT_CONFIGURED, None, 0),
        64: (R.QUOTA_STATE_GROUP_MISSING, 10, 0),
        65: (R.QUOTA_STATE_DELETED, 10, 0),
        66: (R.QUOTA_STATE_FLOOR_MISSING, 10, 0),
    }


def test_quota_view_san_la_gia_tri_luc_chay_dang_chuoi_hai_chu_so():
    majors = _chay(_ho_so(), run=_run(floors={HV1: D("15"), HV2: D("16.5")})).quota_view["majors"]
    assert [m["floor_score"] for m in majors] == ["15.00", "16.50", None]


def test_inputs_floors_la_anh_chup_gia_tri():
    assert R.floors_snapshot({HV2: D("16.5"), HV1: D("15")}) == [
        {"offering_academic_info_id": HV1, "floor_score": "15.00"},
        {"offering_academic_info_id": HV2, "floor_score": "16.50"},
    ]


def test_summary_dem_du_bon_tab_va_tap_xet():
    tom_tat = _run_hon_hop().summary
    assert (sum(tom_tat["tab_counts"].values()), list(tom_tat["tab_counts"]), tom_tat["pool_total"]) == (
        7,
        list(R.REVIEW_TABS),
        5,
    )


def test_diem_tra_ve_dang_chuoi_hai_chu_so():
    dong = _dong(_ho_so())
    assert (dong.scores.as_json(), dong.per_choice[0].as_json()["review_total"]) == (
        {"subject_total": "15.00", "area": "0.75", "object": "0.00", "priority_total": "0.75"},
        "15.75",
    )
