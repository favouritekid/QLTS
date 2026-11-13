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
from app.services import council_document_render_service as bo_dung
from app.services import council_document_template_service as kho_mau

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "hdts20261103_council_document_tables.py"


def _migration():
    spec = importlib.util.spec_from_file_location("hdts20261103", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ba_loai_mau_trung_nhau_o_moi_noi():
    assert m.LOAI_MAU_HOI_DONG == bo_dung.LOAI_MAU == tuple(kho_mau.TEN_LOAI)
    assert set(re.findall(r"'([a-z_]+)'", m.CHECK_LOAI_MAU)) == set(bo_dung.LOAI_MAU)


def test_chuoi_check_cua_model_va_migration_bang_nhau():
    mig = _migration()
    for ten in (
        "CHECK_LOAI_MAU",
        "CHECK_SHA_NOI_DUNG",
        "CHECK_KICH_THUOC",
        "CHECK_MANG_MA",
        "CHECK_MANG_DTO",
    ):
        assert getattr(mig, ten) == getattr(m, ten), ten


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
    assert heads == ["hdts20261113"]
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
        assert getattr(vet, ten) == getattr(m, ten), ten
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
        m.LY_DO_XOA_TOI_DA
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
