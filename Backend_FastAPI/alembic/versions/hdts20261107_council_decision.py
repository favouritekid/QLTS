"""Ghi nhận Quyết định ĐÃ KÝ của bộ văn bản Hội đồng (F230 — lượt I, owner 06-11 C1–C7 + 07-11 E1).

Revision ID: hdts20261107
Revises: hdts20261105
Create Date: 2026-11-07

Đặc tả: ``logs-P5/cong-bo-ket-qua/ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` mục 1 (+ mục 8).

Sáu bảng MỚI + bốn cột MỚI trên ``council_document_set``:

* ``council_document_set_row`` — một dòng của bộ (id hồ sơ, trạng thái lúc dựng, khoá đếm của NV in);
* ``council_decision`` — một tờ giấy đã ký (trúng tuyển / bổ sung / điều chỉnh / văn bản huỷ);
* ``council_decision_row`` — hồ sơ trong một văn bản; cờ ``trang_thai_cha`` do CSDL lan từ văn bản
  (khoá ngoại ghép ON UPDATE CASCADE — K2); dòng khớp ĐÚNG dòng bộ + hồ sơ nguồn (khoá ngoại ghép);
* ``council_decision_scan`` — bản scan PDF;
* ``council_decision_hold`` — nhóm "chờ Admin quyết" (F244, C7);
* ``council_document_event`` — nhật ký sự kiện độc lập (không khoá ngoại).

CHECK / biểu thức chỉ mục viết lại ĐÚNG chuỗi của model (``app/models/council_document.py``) — CSDL
test dựng bằng ``create_all()``; ``tests/unit/test_council_decision_models.py`` so hai bên.

Lệnh chạm bảng ĐANG CÓ (thêm cột / CHECK / chỉ mục trên ``council_document_set``) nằm trong MỘT câu
``DO`` tự đặt ``lock_timeout`` = :data:`TRAN_CHO_KHOA` (khuôn F227 — ``hdts20261104``): quá trần ⇒
:class:`NangCapChoKhoaQuaTran`, không đổi gì.

``downgrade`` XOÁ sáu bảng + bốn cột — tức xoá mọi ghi nhận Quyết định đã ký, scan, nhóm chờ, nhật ký
sự kiện ⇒ FAIL-CLOSED: còn hàng (hoặc cột mới còn giá trị) ⇒ DỪNG, không xoá gì, trừ khi đặt
``COUNCIL_DECISION_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Khoá +
kiểm + xoá là MỘT câu ``DO`` (READ COMMITTED bắt buộc; trần chờ khoá như trên).
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "hdts20261107"
down_revision: Union[str, None] = "hdts20261105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BO = "council_document_set"
DONG_BO = "council_document_set_row"
QD = "council_decision"
DONG_QD = "council_decision_row"
SCAN = "council_decision_scan"
CHO = "council_decision_hold"
SU_KIEN = "council_document_event"
#: Thứ tự xoá khi hạ cấp (bảng phụ thuộc trước).
BANG_MOI_THU_TU_XOA = (CHO, SCAN, SU_KIEN, DONG_QD, QD, DONG_BO)
COT_MOI_CUA_BO = (
    "dung_lai_tu_set_id",
    "ban_ky_so_quyet_dinh",
    "ban_ky_ngay",
    "cho_quyet_dinh_goc_id",
)

LY_DO_TOI_DA = 1000
CHECK_SHA_NOI_DUNG = "sha256 = encode(sha256(noi_dung), 'hex')"
CHECK_KICH_THUOC = "kich_thuoc > 0 AND kich_thuoc = octet_length(noi_dung)"
DIEU_KIEN_DONG_HIEU_LUC = "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL"

CHECK_BO_BAN_KY_DU = "(ban_ky_so_quyet_dinh IS NULL) = (ban_ky_ngay IS NULL)"
CHECK_BO_DUNG_LAI_CO_BAN_KY = (
    "dung_lai_tu_set_id IS NULL OR ban_ky_so_quyet_dinh IS NOT NULL"
)
CHECK_BO_MOT_CHE_DO = "ban_ky_so_quyet_dinh IS NULL OR cho_quyet_dinh_goc_id IS NULL"
CHECK_BO_SO_BAN_KY = (
    "ban_ky_so_quyet_dinh IS NULL OR ban_ky_so_quyet_dinh ~ '^[0-9]{1,6}$'"
)
CHECK_DONG_BO_STT = "stt >= 1"

CHECK_QD_LOAI = "loai IN ('trung_tuyen', 'bo_sung', 'dieu_chinh', 'van_ban_huy')"
CHECK_QD_TRANG_THAI = "trang_thai IN ('hieu_luc', 'het_hieu_luc', 'huy_ghi_nhan')"
CHECK_QD_K3_GOC = "(loai IN ('bo_sung', 'dieu_chinh')) = (goc_id IS NOT NULL)"
CHECK_QD_K3_HUY = "(loai = 'van_ban_huy') = (huy_qd_id IS NOT NULL)"
CHECK_QD_K3_HET = "(trang_thai = 'het_hieu_luc') = (het_hieu_luc_boi_id IS NOT NULL)"
CHECK_QD_K3_VBH = "loai <> 'van_ban_huy' OR trang_thai <> 'het_hieu_luc'"
CHECK_QD_K3_HGN = (
    "(trang_thai = 'huy_ghi_nhan') = (huy_ghi_nhan_boi_id IS NOT NULL "
    "AND huy_ghi_nhan_luc IS NOT NULL AND ly_do_huy_ghi_nhan IS NOT NULL)"
)
CHECK_QD_K3_SO = "so_quyet_dinh ~ '^[0-9]{1,6}$'"
CHECK_QD_K3_PHAM_VI = "pham_vi_so = CAST(EXTRACT(YEAR FROM ngay_ky) AS integer)"
CHECK_QD_K3_LY_DO = (
    "ly_do_huy_ghi_nhan IS NULL OR char_length(btrim(ly_do_huy_ghi_nhan)) > 0"
)
CHECK_QD_K3_TU_TRO = (
    "(goc_id IS NULL OR goc_id <> id) AND (huy_qd_id IS NULL OR huy_qd_id <> id)"
)
CHECK_QD_K4 = "set_id IS NOT NULL OR NOT can_bo OR trang_thai = 'huy_ghi_nhan'"
CHECK_QD_K4B = "can_bo OR set_id IS NULL"
CHECK_QD_K4C = "loai NOT IN ('trung_tuyen', 'bo_sung') OR can_bo"
CHECK_QD_K4D = "loai <> 'van_ban_huy' OR NOT can_bo"
CHECK_QD_SHA_TEP = (
    "sha_tep_quyet_dinh IS NULL OR sha_tep_quyet_dinh ~ '^[0-9a-f]{64}$'"
)
CHECK_QD_SO_HO_SO = "so_ho_so >= 0"
DIEU_KIEN_U1 = "trang_thai <> 'huy_ghi_nhan'"
DIEU_KIEN_U2 = "trang_thai <> 'huy_ghi_nhan' AND set_id IS NOT NULL"
DIEU_KIEN_U4 = "loai = 'van_ban_huy' AND trang_thai = 'hieu_luc'"

CHECK_DONG_QD_K5A = "profile_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DONG_QD_K5B = "set_row_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DONG_QD_K5C = "set_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"  # F257
CHECK_DONG_QD_BO = "bi_bo_boi_id IS NULL OR bi_bo_boi_id <> decision_id"
CHECK_DONG_QD_STT = "stt >= 1"

CHECK_SCAN_KIEU = "kieu = 'application/pdf'"

CHECK_CHO_LY_DO_VAO = "ly_do_vao IN ('qd_bi_huy', 'bi_bo_boi_van_ban_bi_huy')"
CHECK_CHO_TRANG_THAI = "trang_thai IN ('cho_quyet', 'da_cho_xet_lai', 'vo_hieu')"
CHECK_CHO_H3 = "profile_id IS NOT NULL OR trang_thai = 'vo_hieu'"
CHECK_CHO_H4_XL = (
    "trang_thai <> 'da_cho_xet_lai' OR (quyet_boi_id IS NOT NULL "
    "AND quyet_luc IS NOT NULL AND ly_do_quyet IS NOT NULL)"
)
CHECK_CHO_H4_CQ = "trang_thai <> 'cho_quyet' OR quyet_luc IS NULL"
CHECK_CHO_H4_VH = "(trang_thai = 'vo_hieu') = (vo_hieu_luc IS NOT NULL)"
CHECK_CHO_LY_DO = "ly_do_quyet IS NULL OR char_length(btrim(ly_do_quyet)) > 0"
DIEU_KIEN_H1 = "trang_thai = 'cho_quyet'"

LOAI_SU_KIEN = (
    "tao_bo",
    "xoa_bo",
    "tao_bo_dieu_chinh",
    "dung_lai_ban_ky",
    "ghi_nhan",
    "ghi_nhan_dieu_chinh",
    "huy_ghi_nhan",
    "huy_hieu_luc",
    "cho_xet_lai",
    "tai_scan",
)
CHECK_SU_KIEN_LOAI = "loai IN (%s)" % ", ".join("'%s'" % x for x in LOAI_SU_KIEN)
CHECK_SU_KIEN_SO_LIEU = "jsonb_typeof(so_lieu) = 'object'"

CO_CHO_PHEP_XOA = "COUNCIL_DECISION_DOWNGRADE_DROP_DATA_ENABLED"
#: Trần kỹ thuật chờ khoá (F227 — owner 06-11 giữ 10 giây). CÙNG giá trị với
#: ``hdts20261103.TRAN_CHO_KHOA`` / ``hdts20261104.TRAN_CHO_KHOA`` (test khoá ba bản bằng nhau).
TRAN_CHO_KHOA = "10s"

_DAU_CAN_RC = "HDTS20261107_CAN_READ_COMMITTED"
_DAU_CHO_KHOA = "HDTS20261107_CHO_KHOA_QUA_TRAN"


class ConDuLieuQuyetDinh(RuntimeError):
    """downgrade gặp bảng / cột mới còn dữ liệu mà cờ cho phép xoá chưa bật — không xoá gì."""


class HaCapCanReadCommitted(RuntimeError):
    """downgrade chạy ở mức cô lập khác READ COMMITTED — không xoá gì."""


class HaCapChoKhoaQuaTran(RuntimeError):
    """downgrade chờ khoá quá ``TRAN_CHO_KHOA`` — câu ``DO`` lùi, không xoá gì."""


class NangCapChoKhoaQuaTran(RuntimeError):
    """upgrade chờ khoá ``council_document_set`` quá ``TRAN_CHO_KHOA`` — câu ``DO`` lùi, không đổi
    bảng đang có (bảng mới chưa tạo)."""


def _sql_them_cot_bo() -> str:
    """MỘT câu ``DO``: đặt trần chờ khoá NGAY TRONG câu; thêm bốn cột + bốn CHECK + hai chỉ mục
    trên ``council_document_set`` (chạy lại được — ``IF NOT EXISTS``). Quá trần ⇒ ``RAISE`` mang
    dấu ⇒ cả câu lùi."""
    rang_buoc = (
        ("ck_council_document_set_ban_ky_du", CHECK_BO_BAN_KY_DU),
        ("ck_council_document_set_dung_lai_ban_ky", CHECK_BO_DUNG_LAI_CO_BAN_KY),
        ("ck_council_document_set_mot_che_do", CHECK_BO_MOT_CHE_DO),
        ("ck_council_document_set_so_ban_ky", CHECK_BO_SO_BAN_KY),
    )
    ck = "".join(
        "        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '%s') THEN\n"
        '            ALTER TABLE "%s" ADD CONSTRAINT %s CHECK (%s);\n'
        "        END IF;\n" % (ten, BO, ten, bt)
        for ten, bt in rang_buoc
    )
    return (
        "DO $hdts20261107_cot_bo$\n"
        "BEGIN\n"
        "    PERFORM set_config('lock_timeout', '%s', true);\n"
        "    BEGIN\n"
        '        ALTER TABLE "%s"\n'
        "            ADD COLUMN IF NOT EXISTS dung_lai_tu_set_id integer\n"
        '                REFERENCES "%s" (id) ON DELETE SET NULL,\n'
        "            ADD COLUMN IF NOT EXISTS ban_ky_so_quyet_dinh varchar(6),\n"
        "            ADD COLUMN IF NOT EXISTS ban_ky_ngay date,\n"
        "            ADD COLUMN IF NOT EXISTS cho_quyet_dinh_goc_id integer;\n"
        "%s"
        "        CREATE INDEX IF NOT EXISTS ix_council_document_set_dung_lai_tu_set_id\n"
        '            ON "%s" (dung_lai_tu_set_id);\n'
        "        CREATE INDEX IF NOT EXISTS ix_council_document_set_cho_quyet_dinh_goc_id\n"
        '            ON "%s" (cho_quyet_dinh_goc_id);\n'
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261107_cot_bo$"
        % (TRAN_CHO_KHOA, BO, BO, ck, BO, BO, _DAU_CHO_KHOA)
    )


def _sql_ha_cap(cho_phep: bool) -> str:
    """MỘT câu ``DO`` (khuôn ``hdts20261104``): chặn khi không phải READ COMMITTED; trần chờ khoá;
    khoá ACCESS EXCLUSIVE bộ → sáu bảng mới (thứ tự cố định); kiểm còn hàng / cột mới còn giá trị
    bằng ảnh chụp SAU khoá; còn mà cờ chưa bật ⇒ ``RETURN`` (không xoá gì); không thì xoá bảng
    (phụ thuộc trước) rồi bốn cột. ``cho_phep`` chỉ nhận ``bool``."""
    if not isinstance(cho_phep, bool):
        raise TypeError("cho_phep phải là bool")
    khoa = '        LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n' % BO + "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n'
        "        END IF;\n" % (b, b)
        for b in reversed(BANG_MOI_THU_TU_XOA)
    )
    kiem = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            co_hang := co_hang OR EXISTS (SELECT 1 FROM "%s");\n'
        "        END IF;\n" % (b, b)
        for b in BANG_MOI_THU_TU_XOA
    ) + "".join(
        "        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = '%s'\n"
        "                   AND column_name = '%s') THEN\n"
        "            EXECUTE 'SELECT EXISTS (SELECT 1 FROM \"%s\" WHERE %s IS NOT NULL)'\n"
        "                INTO co_cot;\n"
        "            co_hang := co_hang OR co_cot;\n"
        "        END IF;\n" % (BO, c, BO, c)
        for c in COT_MOI_CUA_BO
    )
    xoa = "".join('        DROP TABLE IF EXISTS "%s";\n' % b for b in BANG_MOI_THU_TU_XOA)
    xoa_cot = '        ALTER TABLE "%s" %s;\n' % (
        BO,
        ", ".join("DROP COLUMN IF EXISTS %s" % c for c in reversed(COT_MOI_CUA_BO)),
    )
    return (
        "DO $hdts20261107_ha_cap$\n"
        "DECLARE\n"
        "    co_hang boolean := false;\n"
        "    co_cot boolean := false;\n"
        "BEGIN\n"
        "    IF current_setting('transaction_isolation') <> 'read committed' THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END IF;\n"
        "    PERFORM set_config('lock_timeout', '%s', true);\n"
        "    BEGIN\n"
        "%s%s"
        "        IF co_hang AND NOT %s THEN\n"
        "            RETURN;\n"
        "        END IF;\n"
        "%s%s"
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261107_ha_cap$"
        % (
            _DAU_CAN_RC,
            TRAN_CHO_KHOA,
            khoa,
            kiem,
            "true" if cho_phep else "false",
            xoa,
            xoa_cot,
            _DAU_CHO_KHOA,
        )
    )


def _loi_cua_csdl(e: DBAPIError) -> str:
    # So dấu trên THÔNG BÁO của CSDL (``e.orig``), KHÔNG trên ``str(e)`` (chép cả câu lệnh — bài
    # học lượt G).
    return str(e.orig) if getattr(e, "orig", None) is not None else ""


def upgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(text(_sql_them_cot_bo()))
    except DBAPIError as e:
        if _DAU_CHO_KHOA in _loi_cua_csdl(e):
            raise NangCapChoKhoaQuaTran(
                "Nâng cấp hdts20261107 dừng: chờ khoá bảng bộ văn bản quá %s. Không đổi gì — "
                "chạy lại khi bảng rảnh." % TRAN_CHO_KHOA
            ) from None
        raise

    op.create_table(
        DONG_BO,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("status_luc_dung", sa.String(length=32), nullable=False),
        sa.Column("nv_in_id", sa.BigInteger(), nullable=True),
        sa.Column("admission_path_id", sa.Integer(), nullable=True),
        sa.Column("academic_info_id", sa.Integer(), nullable=True),
        sa.Column("offering_id", sa.Integer(), nullable=True),
        sa.Column("major_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["set_id"], [BO + ".id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["admission_profile.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("set_id", "stt", name="uq_council_document_set_row_stt"),
        sa.UniqueConstraint(
            "set_id", "profile_id", name="uq_council_document_set_row_profile"
        ),
        sa.UniqueConstraint(
            "id", "set_id", "profile_id", name="uq_council_document_set_row_dich"
        ),
        sa.CheckConstraint(CHECK_DONG_BO_STT, name="ck_council_document_set_row_stt"),
        if_not_exists=True,
    )
    for cot in ("set_id", "profile_id"):
        op.create_index(
            "ix_council_document_set_row_%s" % cot, DONG_BO, [cot], if_not_exists=True
        )

    op.create_table(
        QD,
        # ``id`` nằm trong khoá ngoại ghép K6 ⇒ phải khai tự tăng tường minh (như model).
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("loai", sa.String(length=16), nullable=False),
        sa.Column("can_bo", sa.Boolean(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("goc_id", sa.Integer(), nullable=True),
        sa.Column("huy_qd_id", sa.Integer(), nullable=True),
        sa.Column("het_hieu_luc_boi_id", sa.Integer(), nullable=True),
        sa.Column("so_quyet_dinh", sa.String(length=6), nullable=False),
        sa.Column("ngay_ky", sa.Date(), nullable=False),
        sa.Column("pham_vi_so", sa.Integer(), nullable=False),
        sa.Column("trang_thai", sa.String(length=16), nullable=False),
        sa.Column(
            "tham_so_ban_ky", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("so_ho_so", sa.Integer(), nullable=False),
        sa.Column("sha_tep_quyet_dinh", sa.String(length=64), nullable=True),
        sa.Column("xac_nhan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ghi_chu_mau", sa.String(length=LY_DO_TOI_DA), nullable=True),
        sa.Column("ghi_nhan_boi_id", sa.Integer(), nullable=False),
        sa.Column(
            "ghi_nhan_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("huy_ghi_nhan_boi_id", sa.Integer(), nullable=True),
        sa.Column("huy_ghi_nhan_luc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ly_do_huy_ghi_nhan", sa.String(length=LY_DO_TOI_DA), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["set_id"], [BO + ".id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goc_id"], [QD + ".id"]),
        sa.ForeignKeyConstraint(["huy_qd_id"], [QD + ".id"]),
        sa.UniqueConstraint("id", "trang_thai", name="uq_council_decision_id_trang_thai"),
        sa.UniqueConstraint("id", "set_id", name="uq_council_decision_id_set"),
        sa.UniqueConstraint("id", "huy_qd_id", name="uq_council_decision_id_huy"),
        sa.ForeignKeyConstraint(
            ["het_hieu_luc_boi_id", "id"],
            [QD + ".id", QD + ".huy_qd_id"],
            name="fk_council_decision_k6",
        ),
        sa.CheckConstraint(CHECK_QD_LOAI, name="ck_council_decision_loai"),
        sa.CheckConstraint(CHECK_QD_TRANG_THAI, name="ck_council_decision_trang_thai"),
        sa.CheckConstraint(CHECK_QD_K3_GOC, name="ck_council_decision_k3_goc"),
        sa.CheckConstraint(CHECK_QD_K3_HUY, name="ck_council_decision_k3_huy"),
        sa.CheckConstraint(CHECK_QD_K3_HET, name="ck_council_decision_k3_het"),
        sa.CheckConstraint(CHECK_QD_K3_VBH, name="ck_council_decision_k3_vbh"),
        sa.CheckConstraint(CHECK_QD_K3_HGN, name="ck_council_decision_k3_hgn"),
        sa.CheckConstraint(CHECK_QD_K3_SO, name="ck_council_decision_k3_so"),
        sa.CheckConstraint(CHECK_QD_K3_PHAM_VI, name="ck_council_decision_k3_pham_vi"),
        sa.CheckConstraint(CHECK_QD_K3_LY_DO, name="ck_council_decision_k3_ly_do"),
        sa.CheckConstraint(CHECK_QD_K3_TU_TRO, name="ck_council_decision_k3_tu_tro"),
        sa.CheckConstraint(CHECK_QD_K4, name="ck_council_decision_k4"),
        sa.CheckConstraint(CHECK_QD_K4B, name="ck_council_decision_k4b"),
        sa.CheckConstraint(CHECK_QD_K4C, name="ck_council_decision_k4c"),
        sa.CheckConstraint(CHECK_QD_K4D, name="ck_council_decision_k4d"),
        sa.CheckConstraint(CHECK_QD_SHA_TEP, name="ck_council_decision_sha_tep"),
        sa.CheckConstraint(CHECK_QD_SO_HO_SO, name="ck_council_decision_so_ho_so"),
        if_not_exists=True,
    )
    for cot in ("set_id", "goc_id", "huy_qd_id"):
        op.create_index(
            "ix_council_decision_%s" % cot, QD, [cot], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_u1_so",
        QD,
        ["so_quyet_dinh", "pham_vi_so"],
        unique=True,
        postgresql_where=sa.text(DIEU_KIEN_U1),
        if_not_exists=True,
    )
    op.create_index(
        "uq_council_decision_u2_bo",
        QD,
        ["set_id"],
        unique=True,
        postgresql_where=sa.text(DIEU_KIEN_U2),
        if_not_exists=True,
    )
    op.create_index(
        "uq_council_decision_u4_huy",
        QD,
        ["huy_qd_id"],
        unique=True,
        postgresql_where=sa.text(DIEU_KIEN_U4),
        if_not_exists=True,
    )

    op.create_table(
        DONG_QD,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("trang_thai_cha", sa.String(length=16), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("set_row_id", sa.Integer(), nullable=True),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("bi_bo_boi_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bi_bo_boi_id"], [QD + ".id"]),
        sa.ForeignKeyConstraint(
            ["decision_id", "trang_thai_cha"],
            [QD + ".id", QD + ".trang_thai"],
            onupdate="CASCADE",
            name="fk_council_decision_row_k2",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id", "set_id"],
            [QD + ".id", QD + ".set_id"],
            onupdate="CASCADE",
            name="fk_council_decision_row_bo",
        ),
        sa.ForeignKeyConstraint(
            ["set_row_id", "set_id", "profile_id"],
            [DONG_BO + ".id", DONG_BO + ".set_id", DONG_BO + ".profile_id"],
            onupdate="CASCADE",
            ondelete="SET NULL (set_row_id)",
            name="fk_council_decision_row_dong_bo",
        ),
        sa.CheckConstraint(CHECK_DONG_QD_K5A, name="ck_council_decision_row_k5a"),
        sa.CheckConstraint(CHECK_DONG_QD_K5B, name="ck_council_decision_row_k5b"),
        sa.CheckConstraint(CHECK_DONG_QD_K5C, name="ck_council_decision_row_k5c"),
        sa.CheckConstraint(CHECK_DONG_QD_BO, name="ck_council_decision_row_bo"),
        sa.CheckConstraint(CHECK_DONG_QD_STT, name="ck_council_decision_row_stt"),
        sa.UniqueConstraint("decision_id", "stt", name="uq_council_decision_row_stt"),
        sa.UniqueConstraint(
            "decision_id", "set_row_id", name="uq_council_decision_row_u5"
        ),
        if_not_exists=True,
    )
    for cot in ("decision_id", "profile_id", "bi_bo_boi_id"):
        op.create_index(
            "ix_council_decision_row_%s" % cot, DONG_QD, [cot], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_row_u3_ho_so",
        DONG_QD,
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text(DIEU_KIEN_DONG_HIEU_LUC),
        if_not_exists=True,
    )

    op.create_table(
        SCAN,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kich_thuoc", sa.BigInteger(), nullable=False),
        sa.Column("kieu", sa.String(length=64), nullable=False),
        sa.Column("noi_dung", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decision_id"], [QD + ".id"]),
        sa.UniqueConstraint("decision_id"),
        sa.CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_decision_scan_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_KICH_THUOC, name="ck_council_decision_scan_kich_thuoc"
        ),
        sa.CheckConstraint(CHECK_SCAN_KIEU, name="ck_council_decision_scan_kieu"),
        if_not_exists=True,
    )

    op.create_table(
        CHO,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("decision_row_id", sa.Integer(), nullable=False),
        sa.Column("van_ban_huy_id", sa.Integer(), nullable=False),
        sa.Column("ly_do_vao", sa.String(length=32), nullable=False),
        sa.Column("trang_thai", sa.String(length=16), nullable=False),
        sa.Column(
            "tao_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("quyet_boi_id", sa.Integer(), nullable=True),
        sa.Column("quyet_luc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ly_do_quyet", sa.String(length=LY_DO_TOI_DA), nullable=True),
        sa.Column("vo_hieu_boi_id", sa.Integer(), nullable=True),
        sa.Column("vo_hieu_luc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["admission_profile.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["decision_row_id"], [DONG_QD + ".id"]),
        sa.ForeignKeyConstraint(["van_ban_huy_id"], [QD + ".id"]),
        sa.CheckConstraint(
            CHECK_CHO_LY_DO_VAO, name="ck_council_decision_hold_ly_do_vao"
        ),
        sa.CheckConstraint(
            CHECK_CHO_TRANG_THAI, name="ck_council_decision_hold_trang_thai"
        ),
        sa.CheckConstraint(CHECK_CHO_H3, name="ck_council_decision_hold_h3"),
        sa.CheckConstraint(CHECK_CHO_H4_XL, name="ck_council_decision_hold_h4_xl"),
        sa.CheckConstraint(CHECK_CHO_H4_CQ, name="ck_council_decision_hold_h4_cq"),
        sa.CheckConstraint(CHECK_CHO_H4_VH, name="ck_council_decision_hold_h4_vh"),
        sa.CheckConstraint(CHECK_CHO_LY_DO, name="ck_council_decision_hold_ly_do"),
        sa.UniqueConstraint(
            "van_ban_huy_id", "profile_id", name="uq_council_decision_hold_h2"
        ),
        if_not_exists=True,
    )
    for cot in ("profile_id", "van_ban_huy_id"):
        op.create_index(
            "ix_council_decision_hold_%s" % cot, CHO, [cot], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_hold_h1_cho",
        CHO,
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text(DIEU_KIEN_H1),
        if_not_exists=True,
    )

    op.create_table(
        SU_KIEN,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loai", sa.String(length=32), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("hold_id", sa.Integer(), nullable=True),
        sa.Column("nguoi_id", sa.Integer(), nullable=True),
        sa.Column(
            "luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("so_lieu", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(CHECK_SU_KIEN_LOAI, name="ck_council_document_event_loai"),
        sa.CheckConstraint(
            CHECK_SU_KIEN_SO_LIEU, name="ck_council_document_event_so_lieu"
        ),
        if_not_exists=True,
    )
    for cot in ("set_id", "decision_id", "luc"):
        op.create_index(
            "ix_council_document_event_%s" % cot, SU_KIEN, [cot], if_not_exists=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(text(_sql_ha_cap(os.environ.get(CO_CHO_PHEP_XOA) == "1")))
    except DBAPIError as e:
        loi = _loi_cua_csdl(e)
        if _DAU_CAN_RC in loi:
            raise HaCapCanReadCommitted(
                "Hạ cấp hdts20261107 cần mức cô lập READ COMMITTED. Không xoá gì."
            ) from None
        if _DAU_CHO_KHOA in loi:
            raise HaCapChoKhoaQuaTran(
                "Hạ cấp hdts20261107 dừng: chờ khoá quá %s (có giao dịch khác đang dùng bảng). "
                "Không xoá gì, phiên bản không đổi." % TRAN_CHO_KHOA
            ) from None
        raise
    # Câu DO KHÔNG xoá ⇔ còn dữ liệu mà cờ chưa bật ⇒ báo lỗi miền.
    con = [
        b
        for b in BANG_MOI_THU_TU_XOA
        if bind.execute(text("SELECT to_regclass(:b)"), {"b": b}).scalar() is not None
    ]
    if con:
        raise ConDuLieuQuyetDinh(
            "Bảng / cột ghi nhận Quyết định đã ký còn dữ liệu. Không xoá gì. Sao lưu rồi đặt "
            "%s=1 nếu thật sự muốn xoá." % CO_CHO_PHEP_XOA
        )
