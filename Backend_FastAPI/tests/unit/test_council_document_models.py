# -*- coding: utf-8 -*-
"""Model + migration của kho mẫu / bộ văn bản Hội đồng — khoá các chỗ phải TRÙNG nhau.

CSDL test dựng bằng ``create_all()`` (đọc model), production dựng bằng migration
``hdts20261103``: chuỗi CHECK và tên ràng buộc khai hai nơi ⇒ test này so hai bên (không cần
CSDL). Phép so lược đồ thật (cột · ràng buộc · chỉ mục) giữa CSDL dựng bằng migration và CSDL
dựng bằng ``create_all`` chạy ngoài CI, ghi ở báo cáo lượt E1.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models import council_document as m
from app.services import council_document_render_service as render_service
from app.services import council_document_template_service as kho_mau

pytestmark = pytest.mark.unit

#: tên hằng ở MIGRATION (giữ nguyên, tiếng Việt) → tên hằng cùng chuỗi ở model (đã đổi sang tiếng Anh)
TEN_MODEL = {
    "CHECK_BO_BAN_KY_DU": "CHECK_SET_SIGNED_COPY_COMPLETE",
    "CHECK_BO_DUNG_LAI_CO_BAN_KY": "CHECK_SET_REBUILD_HAS_SIGNED_COPY",
    "CHECK_BO_MOT_CHE_DO": "CHECK_SET_ONE_MODE",
    "CHECK_BO_SO_BAN_KY": "CHECK_SET_SIGNED_COPY_NUMBER",
    "CHECK_CHO_H3": "CHECK_HOLD_H3",
    "CHECK_CHO_H4_CQ": "CHECK_HOLD_H4_PENDING",
    "CHECK_CHO_H4_VH": "CHECK_HOLD_H4_VOID",
    "CHECK_CHO_H4_XL": "CHECK_HOLD_H4_RECHECK",
    "CHECK_CHO_LY_DO": "CHECK_HOLD_REASON",
    "CHECK_CHO_LY_DO_VAO": "CHECK_HOLD_ENTRY_REASON",
    "CHECK_CHO_TRANG_THAI": "CHECK_HOLD_STATUS",
    "CHECK_DANH_SACH_TEP": "CHECK_FILE_LIST",
    "CHECK_DONG_BO_STT": "CHECK_SET_ROW_SEQ",
    "CHECK_DONG_QD_BO": "CHECK_DECISION_ROW_SET",
    "CHECK_DONG_QD_K5A": "CHECK_DECISION_ROW_K5A",
    "CHECK_DONG_QD_K5B": "CHECK_DECISION_ROW_K5B",
    "CHECK_DONG_QD_K5C": "CHECK_DECISION_ROW_K5C",
    "CHECK_DONG_QD_STT": "CHECK_DECISION_ROW_SEQ",
    "CHECK_KICH_THUOC": "CHECK_SIZE",
    "CHECK_LOAI_MAU": "CHECK_TEMPLATE_KIND",
    "CHECK_LUOT_BO_KHOP": "CHECK_SUBMISSION_SET_MATCH",
    "CHECK_LUOT_CHO_CO_BO": "CHECK_SUBMISSION_PENDING_HAS_SET",
    "CHECK_LUOT_KET_THUC": "CHECK_SUBMISSION_FINISHED",
    "CHECK_LUOT_QD": "CHECK_SUBMISSION_DECISION",
    "CHECK_LUOT_SHA": "CHECK_SUBMISSION_SHA",
    "CHECK_LUOT_SHA_HEX": "CHECK_SUBMISSION_SHA_HEX",
    "CHECK_LUOT_TRANG_THAI": "CHECK_SUBMISSION_STATUS",
    "CHECK_LY_DO": "CHECK_REASON",
    "CHECK_MANG_DTO": "CHECK_DTO_ARRAY",
    "CHECK_MANG_MA": "CHECK_CODE_ARRAY",
    "CHECK_QD_K3_GOC": "CHECK_DECISION_K3_ROOT",
    "CHECK_QD_K3_HET": "CHECK_DECISION_K3_EXPIRED",
    "CHECK_QD_K3_HGN": "CHECK_DECISION_K3_REVOKED",
    "CHECK_QD_K3_HUY": "CHECK_DECISION_K3_CANCEL",
    "CHECK_QD_K3_LY_DO": "CHECK_DECISION_K3_REASON",
    "CHECK_QD_K3_PHAM_VI": "CHECK_DECISION_K3_SCOPE",
    "CHECK_QD_K3_SO": "CHECK_DECISION_K3_NUMBER",
    "CHECK_QD_K3_TU_TRO": "CHECK_DECISION_K3_SELF_REFERENCE",
    "CHECK_QD_K3_VBH": "CHECK_DECISION_K3_CANCELLATION",
    "CHECK_QD_K4": "CHECK_DECISION_K4",
    "CHECK_QD_K4B": "CHECK_DECISION_K4B",
    "CHECK_QD_K4C": "CHECK_DECISION_K4C",
    "CHECK_QD_K4D": "CHECK_DECISION_K4D",
    "CHECK_QD_LOAI": "CHECK_DECISION_KIND",
    "CHECK_QD_SHA_TEP": "CHECK_DECISION_FILE_SHA",
    "CHECK_QD_SO_HO_SO": "CHECK_DECISION_PROFILE_COUNT",
    "CHECK_QD_TRANG_THAI": "CHECK_DECISION_STATUS",
    "CHECK_SCAN_KIEU": "CHECK_SCAN_TYPE",
    "CHECK_SHA_NOI_DUNG": "CHECK_SHA_CONTENT",
    "CHECK_SU_KIEN_LOAI": "CHECK_EVENT_KIND",
    "CHECK_SU_KIEN_SO_LIEU": "CHECK_EVENT_FIGURES",
    "DIEU_KIEN_DONG_GIU_HO_SO": "ROW_HOLDS_PROFILE_CONDITION",
    "DIEU_KIEN_DONG_HIEU_LUC": "EFFECTIVE_ROW_CONDITION",
    "DIEU_KIEN_H1": "CONDITION_H1",
    "DIEU_KIEN_LUOT_CHO_GUI": "PENDING_SUBMISSION_CONDITION",
    "DIEU_KIEN_U1": "CONDITION_U1",
    "DIEU_KIEN_U2": "CONDITION_U2",
    "DIEU_KIEN_U4": "CONDITION_U4",
    "LY_DO_XOA_TOI_DA": "MAX_DELETE_REASON_LENGTH",
}

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "hdts20261103_council_document_tables.py"


def _migration():
    spec = importlib.util.spec_from_file_location("hdts20261103", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ba_loai_mau_trung_nhau_o_moi_noi():
    assert m.COUNCIL_TEMPLATE_KINDS == render_service.TEMPLATE_KINDS == tuple(kho_mau.KIND_NAMES)
    assert set(re.findall(r"'([a-z_]+)'", m.CHECK_TEMPLATE_KIND)) == set(render_service.TEMPLATE_KINDS)


def test_chuoi_check_cua_model_va_migration_bang_nhau():
    mig = _migration()
    for ten in (
        "CHECK_LOAI_MAU",
        "CHECK_SHA_NOI_DUNG",
        "CHECK_KICH_THUOC",
        "CHECK_MANG_MA",
        "CHECK_MANG_DTO",
    ):
        assert getattr(mig, ten) == getattr(m, TEN_MODEL.get(ten, ten)), ten


def _ten_rang_buoc_model(lop):
    return {
        c.name
        for c in lop.__table__.constraints
        if c.name and not c.name.endswith("_pkey")
    }


def test_ten_rang_buoc_cua_model_co_du_trong_migration():
    nguon = TEP_MIGRATION.read_text(encoding="utf-8")
    trong_mig = set(
        re.findall(r'name="((?:ck|uq)_council_document_[a-z0-9_]+)"', nguon)
    )
    o_model = set()
    for lop in (
        m.CouncilDocumentTemplate,
        m.CouncilDocumentSet,
        m.CouncilDocumentSetFile,
    ):
        o_model |= {
            n for n in _ten_rang_buoc_model(lop) if n.startswith(("ck_", "uq_"))
        }
    # Lượt I: bốn CHECK mới trên ``council_document_set`` do ``hdts20261107`` tạo (khoá ở
    # ``test_council_decision_models.py``) — không thuộc migration 1103.
    cua_1107 = set(
        re.findall(
            r'\("(ck_council_document_set_[a-z_]+)", CHECK_',
            (TEP_MIGRATION.parent / "hdts20261107_council_decision.py").read_text(
                encoding="utf-8"
            ),
        )
    )
    assert len(cua_1107) == 4 and cua_1107 <= o_model
    o_model -= cua_1107
    assert o_model == trong_mig and len(o_model) == 15


def test_cot_bytes_va_pii_la_deferred():
    for lop, cot in (
        (m.CouncilDocumentTemplate, "noi_dung"),
        (m.CouncilDocumentSetFile, "noi_dung"),
        (m.CouncilDocumentSet, "ma_ho_so_dau_vao"),
        (m.CouncilDocumentSet, "snapshot_dto"),
    ):
        assert lop.__mapper__.attrs[cot].deferred, (lop.__name__, cot)
    assert not m.CouncilDocumentSet.__mapper__.attrs["thong_tin_dung"].deferred


def test_khoa_ngoai_tep_xoa_theo_bo():
    fk = next(iter(m.CouncilDocumentSetFile.__table__.c.set_id.foreign_keys))
    assert fk.ondelete == "CASCADE" and fk.column.table.name == "council_document_set"
    dv = next(iter(m.CouncilDocumentSet.__table__.c.unit_id.foreign_keys))
    assert dv.ondelete == "SET NULL"  # đơn vị bị xoá ⇒ bộ THU HẸP về chỉ admin


TEP_MIGRATION_CASBIN = (
    GOC / "alembic" / "versions" / "hdts20261103b_council_document_casbin.py"
)


def _migration_casbin():
    spec = importlib.util.spec_from_file_location("hdts20261103b", TEP_MIGRATION_CASBIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_la_head_duy_nhat_noi_tiep_head_cu():
    cfg = Config(str(GOC / "alembic.ini"))
    cfg.set_main_option("script_location", str(GOC / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    # lượt E3: hai bảng vết nối sau quyền Casbin (E2); lượt F: quyền route cờ giao diện; lượt I:
    # ghi nhận Quyết định đã ký (hdts20261107 nối sau hdts20261105 — khoá ở
    # ``test_council_decision_models.py``); vòng giao diện: K-2 hdts20261111 (khoá cấu hình) + hdts20261112 (lượt gửi
    # ghi nhận) + hdts20261113 (quyền Casbin cho Quản lý ở tải cả bộ / người tạo bộ) — chuỗi khoá cũng ở
    # ``test_council_decision_models.py``. (Ca này lẽ ra phải sửa ở commit K-2 9d406eab: hồi quy của K-2 bỏ sót tệp
    # này — phát hiện ở hồi quy rộng lượt gửi.)
    # Review max PR #724 (R15): MỘT head + chuỗi Hội đồng là TỔ TIÊN của head (không ghim head = revision cuối của tính
    # năng — migration sau này của repo sẽ làm đỏ test này dù chuỗi vẫn đúng). Cùng lối guard một-head của repo.
    assert len(heads) == 1, heads
    list(ScriptDirectory.from_config(cfg).iterate_revisions(heads[0], "hdts20261113"))  # ném nếu không phải tổ tiên
    mig = _migration()
    assert (mig.revision, mig.down_revision) == ("hdts20261103", "v3circ20261011c")
    assert mig.CO_CHO_PHEP_XOA.endswith("_ENABLED")  # cờ CHO PHÉP, mặc định tắt
    cb = _migration_casbin()
    assert (cb.revision, cb.down_revision) == ("hdts20261103b", "hdts20261103")
    vet = _migration_vet()
    assert (vet.revision, vet.down_revision) == ("hdts20261104", "hdts20261103b")
    assert vet.CO_CHO_PHEP_XOA.endswith("_ENABLED")
    co = _migration_co()
    assert (co.revision, co.down_revision) == ("hdts20261105", "hdts20261104")


TEP_MIGRATION_VET = (
    GOC / "alembic" / "versions" / "hdts20261104_council_document_audit.py"
)


def _migration_vet():
    spec = importlib.util.spec_from_file_location("hdts20261104", TEP_MIGRATION_VET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bang_vet_chuoi_check_va_ten_rang_buoc_model_bang_migration():
    vet = _migration_vet()
    for ten in (
        "CHECK_DANH_SACH_TEP",
        "CHECK_LY_DO",
        "CHECK_SHA_HEX",
        "LY_DO_XOA_TOI_DA",
    ):
        assert getattr(vet, ten) == getattr(m, TEN_MODEL.get(ten, ten)), ten
    nguon = TEP_MIGRATION_VET.read_text(encoding="utf-8")
    trong_mig = set(
        re.findall(r'name="((?:ck|uq)_council_document_[a-z0-9_]+)"', nguon)
    )
    o_model = set()
    for lop in (m.CouncilDocumentSetDeletion, m.CouncilDocumentDownloadLog):
        o_model |= {
            n for n in _ten_rang_buoc_model(lop) if n.startswith(("ck_", "uq_"))
        }
    assert o_model == trong_mig and len(o_model) == 8
    assert m.CouncilDocumentSetDeletion.__table__.c.ly_do.type.length == (
        m.MAX_DELETE_REASON_LENGTH
    )


def test_bang_vet_khong_co_khoa_ngoai_nao():
    # Vết xoá + nhật ký tải sống ĐỘC LẬP với bộ (owner 04-11, Codex lần 5): xoá bộ KHÔNG được
    # cascade mất vết — không khoá ngoại tới bộ (hay tới user).
    for lop in (m.CouncilDocumentSetDeletion, m.CouncilDocumentDownloadLog):
        assert not lop.__table__.foreign_keys, lop.__name__
    assert "ForeignKey" not in TEP_MIGRATION_VET.read_text(encoding="utf-8")


TEP_MIGRATION_CO = (
    GOC / "alembic" / "versions" / "hdts20261105_council_document_flags_casbin.py"
)


def _migration_co():
    spec = importlib.util.spec_from_file_location("hdts20261105", TEP_MIGRATION_CO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEP_MIGRATION_VGD = (
    GOC / "alembic" / "versions" / "hdts20261113_council_document_casbin_vong_gd.py"
)


def _migration_vgd():
    spec = importlib.util.spec_from_file_location("hdts20261113", TEP_MIGRATION_VGD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quyen_manager_trong_template_co_migration_cap():
    # Production KHÔNG tự đồng bộ template ⇒ mọi dòng manager của API văn bản Hội đồng
    # trong template PHẢI là đúng các dòng migration chèn — hdts20261103b (ba route đọc bộ) +
    # hdts20261105 (route cờ giao diện, lượt F) + hdts20261113 (tải cả bộ + người tạo bộ, vòng giao diện) — và
    # ngược lại.
    from app.casbin_config.policy_templates import (
        ACCOUNTANT_TEMPLATE,
        MANAGER_TEMPLATE,
        OFFICER_TEMPLATE,
    )

    cb = _migration_casbin()
    co = _migration_co()
    vgd = _migration_vgd()
    tien_to = "/api/admission-config/council-documents"
    template = {
        ("role:manager", p["object"], p["action"], p.get("eft", "allow"))
        for p in MANAGER_TEMPLATE["policies"]
        if p["object"].startswith(tien_to)
    }
    assert template == set(cb.POLICIES) | set(co.POLICIES) | set(vgd.POLICIES)
    assert len(template) == 6
    assert co.POLICIES == (("role:manager", tien_to + "/quyen", "GET", "allow"),)
    assert vgd.POLICIES == (
        ("role:manager", tien_to + "/sets/{set_id}/tai-ca-bo", "GET", "allow"),
        ("role:manager", tien_to + "/nguoi-tao-bo", "GET", "allow"),
    )
    assert (vgd.revision, vgd.down_revision) == ("hdts20261113", "hdts20261112")
    # hạ cấp mỗi bên chỉ xoá dòng của mình
    assert len({co.TEMPLATE_ID, cb.TEMPLATE_ID, vgd.TEMPLATE_ID}) == 3
    assert all(p[2] == "GET" for p in cb.POLICIES + co.POLICIES + vgd.POLICIES)  # manager CHỈ ĐỌC
    for t in (OFFICER_TEMPLATE, ACCOUNTANT_TEMPLATE):
        assert not [p for p in t["policies"] if p["object"].startswith(tien_to)]


# Route CHỈ ADMIN của lượt E3 (owner 04-11, J1 dòng 29–31) — KHÔNG vai nào ngoài admin có dòng
# Casbin khớp (so bằng ĐÚNG hàm khớp của mô hình: keyMatch4 + regexMatch).
ROUTE_CHI_ADMIN = (
    ("DELETE", "/api/admission-config/council-documents/sets/1"),
    ("GET", "/api/admission-config/council-documents/sets/1/ma-ho-so"),
    ("GET", "/api/admission-config/council-documents/nhat-ky-tai"),
    ("GET", "/api/admission-config/council-documents/nhat-ky-xoa"),
    # Lượt I (F230) — ghi nhận Quyết định đã ký: CHỈ admin (J1 dòng 9, C7)
    ("POST", "/api/admission-config/council-documents/decisions"),
    ("GET", "/api/admission-config/council-documents/decisions"),
    ("GET", "/api/admission-config/council-documents/decisions/1"),
    ("GET", "/api/admission-config/council-documents/decisions/1/scan"),
    ("POST", "/api/admission-config/council-documents/decisions/1/huy-ghi-nhan"),
    ("POST", "/api/admission-config/council-documents/decisions/1/huy-hieu-luc"),
    ("POST", "/api/admission-config/council-documents/decisions/1/bo-dieu-chinh"),
    ("POST", "/api/admission-config/council-documents/decisions/1/dieu-chinh"),
    ("POST", "/api/admission-config/council-documents/sets/1/dung-lai-ban-ky"),
    ("GET", "/api/admission-config/council-documents/sets/1/so-voi-hien-tai"),
    ("GET", "/api/admission-config/council-documents/decision-holds"),
    ("POST", "/api/admission-config/council-documents/decision-holds/1/cho-xet-lai"),
    ("GET", "/api/admission-config/council-documents/su-kien"),
)


def test_route_chi_admin_khong_vai_nao_khac_co_dong_casbin():
    from casbin.util.builtin_operators import key_match4, regex_match

    from app.casbin_config.policy_templates import POLICY_TEMPLATES

    assert set(POLICY_TEMPLATES) >= {"admin", "manager", "officer", "accountant"}
    lot = [
        (vai, method, duong)
        for vai, t in POLICY_TEMPLATES.items()
        if vai != "admin"
        for p in t["policies"]
        for method, duong in ROUTE_CHI_ADMIN
        if key_match4(duong, p["object"])
        and regex_match(method, p["action"])
        and p.get("eft", "allow") == "allow"
    ]
    assert lot == []
    cb, co = _migration_casbin(), _migration_co()
    assert not [
        (method, duong)
        for _, v1, v2, _ in cb.POLICIES + co.POLICIES
        for method, duong in ROUTE_CHI_ADMIN
        if key_match4(duong, v1) and regex_match(method, v2)
    ]
