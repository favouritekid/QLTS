# app/models/council_document.py
"""Kho mẫu + bộ văn bản Hội đồng tuyển sinh (giai đoạn 1 kế hoạch "Lần xét tuyển").

Ba bảng, chủ sở hữu DDL là migration ``hdts20261103``; CHECK / UNIQUE khai Ở CẢ model lẫn
migration vì CSDL test dựng bằng ``Base.metadata.create_all()``.

* ``council_document_template`` — mẫu Word do admin tải lên (mẫu thật KHÔNG nằm trong kho mã).
  Mỗi loại mẫu áp theo NGÀY KÝ của văn bản: ``hieu_luc_tu`` lớn nhất ≤ ngày ký (``Y-TUONG``
  J1 dòng 7). Cùng loại + cùng ngày hiệu lực ⇒ UNIQUE.
* ``council_document_set`` — một lần dựng bộ văn bản: ai, lúc nào, mốc chụp của giao dịch đọc
  hồ sơ, đơn vị (NULL = nhiều đơn vị / không xác định ⇒ chỉ admin xem — J1 dòng 9), danh
  sách mã đầu vào ĐÚNG THỨ TỰ + ảnh chụp DTO đã đưa vào bộ dựng (DỮ LIỆU CÁ NHÂN — cùng quyền
  và hạn lưu như tệp sinh), metadata của bộ dựng (luật, thư viện, id + sha mẫu, sha từng tệp).
* ``council_document_set_file`` — bytes NGUYÊN của từng tệp bộ dựng trả về. Tải lại = đọc
  bytes đã lưu, KHÔNG dựng lại (phép tất định chỉ kiểm từng phần zip, không bảo đảm sha toàn
  tệp giữa hai lần dựng).

Nội dung (``noi_dung``) và hai cột PII của bộ là cột *deferred*: liệt kê không nạp chúng.
CSDL tự canh toàn vẹn: ``kich_thuoc`` = ``octet_length(noi_dung)`` > 0, ``sha256`` = sha-256
hex (chữ thường) của chính ``noi_dung`` (hàm ``sha256()`` của PostgreSQL ≥ 11 — kéo theo
luôn định dạng 64 ký tự hex), số phần tử của hai mảng JSON = ``so_ho_so``.

Hai bảng VẾT (lượt E3, migration ``hdts20261104`` — owner 04-11, J1 dòng 29 / 31) sống ĐỘC
LẬP với bộ: KHÔNG khoá ngoại tới ``council_document_set`` (xoá bộ không cascade mất vết) và
tới ``user`` (giữ nguyên id người làm); KHÔNG danh sách CCCD, KHÔNG DTO, KHÔNG bytes:

* ``council_document_set_deletion`` — Admin xoá một bộ: id bộ, số hồ sơ, danh sách tệp (thứ
  tự, path, sha256, kích thước), người xoá, lúc xoá, lý do bắt buộc. Ghi CÙNG giao dịch với
  lệnh xoá. Xoá trên phần mềm KHÔNG xoá bộ khỏi các bản sao lưu đã có.
* ``council_document_download_log`` — mỗi lần máy chủ CẤP một tệp: người, bộ, thứ tự tệp,
  path, sha256, lúc. Ghi BỀN (commit) TRƯỚC khi trả bytes; không tuyên bố người dùng đã nhận.
"""

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import SYSTEM_CONSULTATION_METHOD

from .base import Base

#: Ba loại mẫu — PHẢI trùng ``LOAI_MAU`` của bộ dựng; test khoá hai bên bằng nhau.
LOAI_MAU_HOI_DONG = ("bien_ban", "quyet_dinh", "danh_sach")

#: Biểu thức CHECK dùng chung cho model (CSDL test) — migration viết lại đúng chuỗi này;
#: ``tests/unit/test_council_document_models.py`` so ba nơi.
CHECK_LOAI_MAU = "loai IN ('bien_ban', 'quyet_dinh', 'danh_sach')"
CHECK_SHA_NOI_DUNG = "sha256 = encode(sha256(noi_dung), 'hex')"
CHECK_KICH_THUOC = "kich_thuoc > 0 AND kich_thuoc = octet_length(noi_dung)"
CHECK_MANG_MA = (
    "jsonb_typeof(ma_ho_so_dau_vao) = 'array' "
    "AND jsonb_array_length(ma_ho_so_dau_vao) = so_ho_so"
)
CHECK_MANG_DTO = (
    "jsonb_typeof(snapshot_dto) = 'array' "
    "AND jsonb_array_length(snapshot_dto) = so_ho_so"
)
# -- hai bảng vết (migration hdts20261104) — migration viết lại đúng các chuỗi này --
#: Trần KỸ THUẬT độ dài lý do xoá (ký tự) — không phải luật nghiệp vụ: đủ một đoạn giải
#: thích, chặn thân request phình vào bảng vết (mỗi byte vào bản sao lưu).
LY_DO_XOA_TOI_DA = 1000
CHECK_DANH_SACH_TEP = (
    "jsonb_typeof(danh_sach_tep) = 'array' "
    "AND jsonb_array_length(danh_sach_tep) = so_tep"
)
CHECK_LY_DO = "char_length(btrim(ly_do)) > 0"
CHECK_SHA_HEX = "sha256 ~ '^[0-9a-f]{64}$'"

# ═══════════ Lượt I (F230) — ghi nhận Quyết định ĐÃ KÝ (migration hdts20261107) ═══════════
# Đặc tả: logs-P5/cong-bo-ket-qua/ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md mục 1 (+ mục 8).
# Mọi chuỗi dưới đây migration viết lại ĐÚNG như thế; ``tests/unit/test_council_decision_models.py``
# so model ↔ migration.
LOAI_VAN_BAN = ("trung_tuyen", "bo_sung", "dieu_chinh", "van_ban_huy")
TRANG_THAI_VAN_BAN = ("hieu_luc", "het_hieu_luc", "huy_ghi_nhan")
#: "Dòng còn hiệu lực" — MỘT biểu thức cho U3 (model + migration), hàm hỏi tình trạng và cột của
#: cổng dựng bộ (``SQL_COT_TINH_TRANG_QD``). Tên cột không kèm bí danh bảng (dùng được trong câu
#: con ``FROM council_decision_row``).
DIEU_KIEN_DONG_HIEU_LUC = "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL"
#: Hồ sơ "có tên" trong văn bản chưa huỷ ghi nhận — ĐÚNG điều kiện CSDL giữ liên kết (K5a): xoá
#: cứng hồ sơ bị chặn. Service báo trước bằng CHÍNH chuỗi này.
DIEU_KIEN_DONG_GIU_HO_SO = "trang_thai_cha <> 'huy_ghi_nhan'"
#: Tiền tố dấu "Đã trúng tuyển theo QĐ số …" của 182 hồ sơ nhập từ AppSheet (công cụ
#: ``cong-cu-nhap-appsheet/nhap_ho_so.py``: dòng 1 của ``ghi_chu_tu_van_dau`` — ghi chú lần tư vấn
#: ``method = 'system'`` và tiền tố của ``revision_reason``). Owner 07-11 E1: em mang dấu áp CÙNG
#: luật như em có Quyết định hiệu lực.
DAU_APPSHEET_TIEN_TO = "Đã trúng tuyển theo QĐ số "
assert not any(k in DAU_APPSHEET_TIEN_TO for k in "%_\\'"), "tiền tố dùng trong LIKE"
assert "'" not in SYSTEM_CONSULTATION_METHOD
#: Biểu thức DUY NHẤT của dấu AppSheet (hồ sơ bí danh ``p``) — cổng dựng bộ, ghi nhận, chốt chuyển
#: trạng thái, cờ giao diện đều đọc qua đây. KHÔNG lọc ``deleted_at`` của lần tư vấn (fail-closed).
SQL_DAU_APPSHEET = (
    "(COALESCE(p.revision_reason, '') LIKE '%s%%' "
    "OR EXISTS (SELECT 1 FROM consultation c_dau WHERE c_dau.lead_id = p.lead_id "
    "AND c_dau.method = '%s' AND COALESCE(c_dau.notes, '') LIKE '%s%%'))"
    % (DAU_APPSHEET_TIEN_TO, SYSTEM_CONSULTATION_METHOD, DAU_APPSHEET_TIEN_TO)
)
#: Các cột tình trạng Quyết định của MỘT hồ sơ (bí danh ``p``) — dùng nguyên văn trong
#: ``SQL_KIEM_NGUON`` (cổng dựng bộ, giao dịch chỉ đọc) và trong hàm hỏi
#: ``council_decision_status_service`` (test khoá hai nơi cùng chuỗi + cùng kết quả).
SQL_COT_TINH_TRANG_QD = (
    "(SELECT min(decision_id) FROM council_decision_row "
    "WHERE profile_id = p.id AND (%s)) AS qd_hieu_luc_id, "
    "(SELECT COALESCE(d_qd.goc_id, d_qd.id) FROM council_decision d_qd "
    "WHERE d_qd.id = (SELECT min(decision_id) FROM council_decision_row "
    "WHERE profile_id = p.id AND (%s))) AS qd_chuoi_id, "
    "(SELECT min(id) FROM council_decision_hold "
    "WHERE profile_id = p.id AND trang_thai = 'cho_quyet') AS cho_quyet_id, "
    "EXISTS (SELECT 1 FROM council_decision_hold "
    "WHERE profile_id = p.id AND trang_thai = 'da_cho_xet_lai') AS da_cho_xet_lai, "
    "EXISTS (SELECT 1 FROM council_decision_row "
    "WHERE profile_id = p.id AND (%s)) AS co_ten_van_ban, "
    "%s AS dau_appsheet"
    % (
        DIEU_KIEN_DONG_HIEU_LUC,
        DIEU_KIEN_DONG_HIEU_LUC,
        DIEU_KIEN_DONG_GIU_HO_SO,
        SQL_DAU_APPSHEET,
    )
)

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
#: C1 (owner 06-11): số Quyết định không trùng TRONG năm dương lịch của ngày ký.
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
#: U1 — một số trong sổ chỉ dùng một lần (số của văn bản bị huỷ hiệu lực VẪN là số đã dùng — C1).
DIEU_KIEN_U1 = "trang_thai <> 'huy_ghi_nhan'"
#: U2 — một bộ ↔ tối đa một văn bản chưa huỷ ghi nhận.
DIEU_KIEN_U2 = "trang_thai <> 'huy_ghi_nhan' AND set_id IS NOT NULL"
#: U4 — một văn bản ↔ tối đa một văn bản huỷ còn sống.
DIEU_KIEN_U4 = "loai = 'van_ban_huy' AND trang_thai = 'hieu_luc'"

CHECK_DONG_QD_K5A = "profile_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DONG_QD_K5B = "set_row_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
#: K5c (F257 — Codex lần 14): ``set_id`` nằm trong HAI khoá ngoại ghép (``fk_council_decision_row_bo``,
#: ``fk_council_decision_row_dong_bo``). ``MATCH SIMPLE`` bỏ qua khoá ngoại có cột NULL ⇒ thiếu CHECK này
#: thì dòng chưa huỷ ghi nhận mang ``set_id`` NULL + ``set_row_id`` của bộ + hồ sơ KHÁC vượt cả hai khoá
#: ngoại lẫn K5a / K5b (gắn sai hồ sơ; bộ đếm lấy khoá từ dòng bộ). Dòng của văn bản đã huỷ ghi nhận được
#: NULL (xoá bộ ⇒ ``council_decision.set_id`` SET NULL ⇒ ON UPDATE CASCADE lan xuống dòng).
CHECK_DONG_QD_K5C = "set_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DONG_QD_BO = "bi_bo_boi_id IS NULL OR bi_bo_boi_id <> decision_id"
CHECK_DONG_QD_STT = "stt >= 1"

LOAI_SCAN = "application/pdf"
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


class CouncilDocumentTemplate(Base):
    """Một mẫu Word của kho mẫu (bytes + sha256 + ngày hiệu lực)."""

    __tablename__ = "council_document_template"
    __table_args__ = (
        UniqueConstraint(
            "loai", "hieu_luc_tu", name="uq_council_document_template_loai_hieu_luc"
        ),
        CheckConstraint(CHECK_LOAI_MAU, name="ck_council_document_template_loai"),
        CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_document_template_sha256_noi_dung"
        ),
        CheckConstraint(
            CHECK_KICH_THUOC, name="ck_council_document_template_kich_thuoc"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loai: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="bien_ban | quyet_dinh | danh_sach"
    )
    hieu_luc_tu: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Áp cho văn bản có ngày ký >= ngày này (mẫu mới nhất ≤ ngày ký thắng)",
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kich_thuoc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    noi_dung: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, deferred=True, comment="Bytes tệp .docx"
    )
    nguoi_tai_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tai_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ghi_chu: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class CouncilDocumentSet(Base):
    """Một bộ văn bản Hội đồng đã dựng (metadata + ảnh chụp đầu vào)."""

    __tablename__ = "council_document_set"
    __table_args__ = (
        CheckConstraint("so_ho_so > 0", name="ck_council_document_set_so_ho_so"),
        CheckConstraint("so_tep > 0", name="ck_council_document_set_so_tep"),
        CheckConstraint(
            "kich_thuoc_tong > 0", name="ck_council_document_set_kich_thuoc_tong"
        ),
        CheckConstraint(CHECK_MANG_MA, name="ck_council_document_set_ma_dau_vao"),
        CheckConstraint(CHECK_MANG_DTO, name="ck_council_document_set_snapshot_dto"),
        # Lượt I (F230, migration hdts20261107) — ba chế độ của bộ: thường / tái dựng bản ký
        # (``ban_ky_*``) / dữ liệu cho văn bản điều chỉnh (``cho_quyet_dinh_goc_id``).
        CheckConstraint(CHECK_BO_BAN_KY_DU, name="ck_council_document_set_ban_ky_du"),
        CheckConstraint(
            CHECK_BO_DUNG_LAI_CO_BAN_KY, name="ck_council_document_set_dung_lai_ban_ky"
        ),
        CheckConstraint(CHECK_BO_MOT_CHE_DO, name="ck_council_document_set_mot_che_do"),
        CheckConstraint(CHECK_BO_SO_BAN_KY, name="ck_council_document_set_so_ban_ky"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nguoi_tao_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tao_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    moc_chup: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="transaction_timestamp() của giao dịch đọc REPEATABLE READ READ ONLY",
    )
    # NULL = bộ nhiều đơn vị / không xác định ⇒ chỉ admin xem (J1 dòng 9). Đơn vị bị xoá ⇒
    # SET NULL: bộ THU HẸP về chỉ admin, không bao giờ mở rộng.
    unit_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("organization_unit.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trinh_do: Mapped[str] = mapped_column(String(64), nullable=False)
    so_ho_so: Mapped[int] = mapped_column(Integer, nullable=False)
    so_tep: Mapped[int] = mapped_column(Integer, nullable=False)
    kich_thuoc_tong: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tham_so_quyet_dinh: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    # Hai cột DỮ LIỆU CÁ NHÂN (CCCD, họ tên, ngày sinh, …) — deferred, không bao giờ log.
    ma_ho_so_dau_vao: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, deferred=True, comment="Mã hồ sơ đầu vào, ĐÚNG THỨ TỰ"
    )
    snapshot_dto: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB,
        nullable=False,
        deferred=True,
        comment="DTO đã đưa vào bộ dựng, cùng thứ tự với mã đầu vào",
    )
    thong_tin_dung: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Luật, thư viện, id + sha mẫu, sha từng tệp, giao dịch đọc",
    )
    # Lượt I (F230): bộ TÁI DỰNG bản ký trỏ bộ in ban đầu; số / ngày trên giấy mà ghi nhận phải
    # khớp. Bộ in ban đầu bị xoá ⇒ SET NULL (bộ tái dựng giữ ảnh chụp riêng); ``ban_ky_*`` là dấu
    # "bộ tái dựng" bền.
    dung_lai_tu_set_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("council_document_set.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ban_ky_so_quyet_dinh: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)
    ban_ky_ngay: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Bộ dữ liệu cho văn bản ĐIỀU CHỈNH của chuỗi Quyết định này (C6). Số nguyên, KHÔNG khoá ngoại
    # (tránh khoá ngoại vòng bộ ↔ văn bản; văn bản không bao giờ bị xoá — không có route, các
    # dòng giữ khoá ngoại RESTRICT); chỉ service ghi, từ một văn bản đã khoá.
    cho_quyet_dinh_goc_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )


class CouncilDocumentSetFile(Base):
    """Bytes nguyên của một tệp trong bộ văn bản."""

    __tablename__ = "council_document_set_file"
    __table_args__ = (
        UniqueConstraint("set_id", "path", name="uq_council_document_set_file_path"),
        UniqueConstraint(
            "set_id", "thu_tu", name="uq_council_document_set_file_thu_tu"
        ),
        CheckConstraint("thu_tu >= 1", name="ck_council_document_set_file_thu_tu"),
        CheckConstraint("path <> ''", name="ck_council_document_set_file_path"),
        CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_document_set_file_sha256_noi_dung"
        ),
        CheckConstraint(
            CHECK_KICH_THUOC, name="ck_council_document_set_file_kich_thuoc"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("council_document_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thu_tu: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Thứ tự tệp như bộ dựng trả về (từ 1)"
    )
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kich_thuoc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    noi_dung: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)


class CouncilDocumentSetDeletion(Base):
    """VẾT XOÁ một bộ văn bản (J1 dòng 29). ``set_id`` KHÔNG là khoá ngoại: bộ đã bị xoá thì
    vết vẫn còn và vẫn truy được bộ / tệp / sha. Không danh sách CCCD, không DTO."""

    __tablename__ = "council_document_set_deletion"
    __table_args__ = (
        UniqueConstraint("set_id", name="uq_council_document_set_deletion_set_id"),
        CheckConstraint(
            "so_ho_so > 0", name="ck_council_document_set_deletion_so_ho_so"
        ),
        CheckConstraint("so_tep > 0", name="ck_council_document_set_deletion_so_tep"),
        CheckConstraint(
            CHECK_DANH_SACH_TEP, name="ck_council_document_set_deletion_danh_sach_tep"
        ),
        CheckConstraint(CHECK_LY_DO, name="ck_council_document_set_deletion_ly_do"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="id bộ đã xoá — KHÔNG khoá ngoại (vết độc lập)"
    )
    so_ho_so: Mapped[int] = mapped_column(Integer, nullable=False)
    so_tep: Mapped[int] = mapped_column(Integer, nullable=False)
    danh_sach_tep: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        comment="[{thu_tu, path, sha256, kich_thuoc}] — không bytes, không dữ liệu cá nhân",
    )
    nguoi_xoa_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="id người xoá — KHÔNG khoá ngoại (vết độc lập)"
    )
    xoa_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    ly_do: Mapped[str] = mapped_column(String(LY_DO_XOA_TOI_DA), nullable=False)


class CouncilDocumentDownloadLog(Base):
    """NHẬT KÝ TẢI tệp bộ văn bản (J1 dòng 31) — một dòng mỗi lần máy chủ CẤP một tệp, ghi
    bền TRƯỚC khi trả bytes. ``set_id`` KHÔNG là khoá ngoại: xoá bộ không làm mất nhật ký.
    """

    __tablename__ = "council_document_download_log"
    __table_args__ = (
        CheckConstraint("thu_tu >= 1", name="ck_council_document_download_log_thu_tu"),
        CheckConstraint("path <> ''", name="ck_council_document_download_log_path"),
        CheckConstraint(CHECK_SHA_HEX, name="ck_council_document_download_log_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="id bộ — KHÔNG khoá ngoại (nhật ký sống độc lập khi bộ bị xoá)",
    )
    thu_tu: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    nguoi_tai_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="id người tải — KHÔNG khoá ngoại (vết độc lập)"
    )
    tai_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


# ═══════════════════════ Lượt I (F230) — dòng bộ + Quyết định đã ký ════════════════════════
class CouncilDocumentSetRow(Base):
    """MỘT dòng của bộ văn bản (ghi cùng SAVEPOINT với bộ): id hồ sơ đọc trong CÙNG giao dịch chỉ
    đọc, trạng thái lúc dựng, khoá đếm của nguyện vọng in (ảnh chụp — số nguyên KHÔNG khoá ngoại).
    Hồ sơ bị xoá cứng ⇒ ``profile_id`` NULL (dòng QĐ của văn bản chưa huỷ ghi nhận chặn việc ấy —
    K5a qua ``fk_council_decision_row_dong_bo``)."""

    __tablename__ = "council_document_set_row"
    __table_args__ = (
        UniqueConstraint("set_id", "stt", name="uq_council_document_set_row_stt"),
        UniqueConstraint(
            "set_id", "profile_id", name="uq_council_document_set_row_profile"
        ),
        UniqueConstraint(
            "id", "set_id", "profile_id", name="uq_council_document_set_row_dich"
        ),
        CheckConstraint(CHECK_DONG_BO_STT, name="ck_council_document_set_row_stt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("council_document_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status_luc_dung: Mapped[str] = mapped_column(String(32), nullable=False)
    nv_in_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    admission_path_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    academic_info_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    offering_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    major_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class CouncilDecision(Base):
    """MỘT tờ giấy đã ký: Quyết định trúng tuyển / bổ sung / điều chỉnh / văn bản huỷ. Không thao
    tác nào sửa NỘI DUNG một bản ghi đã có — chỉ đổi ``trang_thai`` (+ cột huỷ). Ràng buộc K1–K6,
    U1, U2, U4: đặc tả mục 1.8."""

    __tablename__ = "council_decision"
    __table_args__ = (
        CheckConstraint(CHECK_QD_LOAI, name="ck_council_decision_loai"),
        CheckConstraint(CHECK_QD_TRANG_THAI, name="ck_council_decision_trang_thai"),
        CheckConstraint(CHECK_QD_K3_GOC, name="ck_council_decision_k3_goc"),
        CheckConstraint(CHECK_QD_K3_HUY, name="ck_council_decision_k3_huy"),
        CheckConstraint(CHECK_QD_K3_HET, name="ck_council_decision_k3_het"),
        CheckConstraint(CHECK_QD_K3_VBH, name="ck_council_decision_k3_vbh"),
        CheckConstraint(CHECK_QD_K3_HGN, name="ck_council_decision_k3_hgn"),
        CheckConstraint(CHECK_QD_K3_SO, name="ck_council_decision_k3_so"),
        CheckConstraint(CHECK_QD_K3_PHAM_VI, name="ck_council_decision_k3_pham_vi"),
        CheckConstraint(CHECK_QD_K3_LY_DO, name="ck_council_decision_k3_ly_do"),
        CheckConstraint(CHECK_QD_K3_TU_TRO, name="ck_council_decision_k3_tu_tro"),
        CheckConstraint(CHECK_QD_K4, name="ck_council_decision_k4"),
        CheckConstraint(CHECK_QD_K4B, name="ck_council_decision_k4b"),
        CheckConstraint(CHECK_QD_K4C, name="ck_council_decision_k4c"),
        CheckConstraint(CHECK_QD_K4D, name="ck_council_decision_k4d"),
        CheckConstraint(CHECK_QD_SHA_TEP, name="ck_council_decision_sha_tep"),
        CheckConstraint(CHECK_QD_SO_HO_SO, name="ck_council_decision_so_ho_so"),
        UniqueConstraint("id", "trang_thai", name="uq_council_decision_id_trang_thai"),
        UniqueConstraint("id", "set_id", name="uq_council_decision_id_set"),
        UniqueConstraint("id", "huy_qd_id", name="uq_council_decision_id_huy"),
        ForeignKeyConstraint(
            ["het_hieu_luc_boi_id", "id"],
            ["council_decision.id", "council_decision.huy_qd_id"],
            name="fk_council_decision_k6",
        ),
        Index(
            "uq_council_decision_u1_so",
            "so_quyet_dinh",
            "pham_vi_so",
            unique=True,
            postgresql_where=text(DIEU_KIEN_U1),
        ),
        Index(
            "uq_council_decision_u2_bo",
            "set_id",
            unique=True,
            postgresql_where=text(DIEU_KIEN_U2),
        ),
        Index(
            "uq_council_decision_u4_huy",
            "huy_qd_id",
            unique=True,
            postgresql_where=text(DIEU_KIEN_U4),
        ),
    )

    # ``id`` nằm trong khoá ngoại ghép K6 ⇒ SQLAlchemy KHÔNG tự coi là cột tự tăng — khai tường minh.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loai: Mapped[str] = mapped_column(String(16), nullable=False)
    can_bo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    set_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("council_document_set.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    goc_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("council_decision.id"), nullable=True, index=True
    )
    huy_qd_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("council_decision.id"), nullable=True, index=True
    )
    het_hieu_luc_boi_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    so_quyet_dinh: Mapped[str] = mapped_column(String(6), nullable=False)
    ngay_ky: Mapped[date] = mapped_column(Date, nullable=False)
    pham_vi_so: Mapped[int] = mapped_column(Integer, nullable=False)
    trang_thai: Mapped[str] = mapped_column(String(16), nullable=False)
    tham_so_ban_ky: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    so_ho_so: Mapped[int] = mapped_column(Integer, nullable=False)
    sha_tep_quyet_dinh: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    xac_nhan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ghi_chu_mau: Mapped[Optional[str]] = mapped_column(
        String(LY_DO_XOA_TOI_DA), nullable=True
    )
    ghi_nhan_boi_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="id người ghi nhận — KHÔNG khoá ngoại (vết)"
    )
    ghi_nhan_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    huy_ghi_nhan_boi_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    huy_ghi_nhan_luc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ly_do_huy_ghi_nhan: Mapped[Optional[str]] = mapped_column(
        String(LY_DO_XOA_TOI_DA), nullable=True
    )


class CouncilDecisionRow(Base):
    """Một hồ sơ trong một văn bản. ``trang_thai_cha`` do CSDL lan từ văn bản (K2 — khoá ngoại ghép
    ON UPDATE CASCADE); dòng = ĐÚNG dòng bộ nguồn của ĐÚNG bộ của văn bản, đúng hồ sơ nguồn
    (``fk_council_decision_row_bo`` + ``fk_council_decision_row_dong_bo``)."""

    __tablename__ = "council_decision_row"
    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "trang_thai_cha"],
            ["council_decision.id", "council_decision.trang_thai"],
            onupdate="CASCADE",
            name="fk_council_decision_row_k2",
        ),
        ForeignKeyConstraint(
            ["decision_id", "set_id"],
            ["council_decision.id", "council_decision.set_id"],
            onupdate="CASCADE",
            name="fk_council_decision_row_bo",
        ),
        ForeignKeyConstraint(
            ["set_row_id", "set_id", "profile_id"],
            [
                "council_document_set_row.id",
                "council_document_set_row.set_id",
                "council_document_set_row.profile_id",
            ],
            onupdate="CASCADE",
            ondelete="SET NULL (set_row_id)",
            name="fk_council_decision_row_dong_bo",
        ),
        CheckConstraint(CHECK_DONG_QD_K5A, name="ck_council_decision_row_k5a"),
        CheckConstraint(CHECK_DONG_QD_K5B, name="ck_council_decision_row_k5b"),
        CheckConstraint(CHECK_DONG_QD_K5C, name="ck_council_decision_row_k5c"),
        CheckConstraint(CHECK_DONG_QD_BO, name="ck_council_decision_row_bo"),
        CheckConstraint(CHECK_DONG_QD_STT, name="ck_council_decision_row_stt"),
        UniqueConstraint("decision_id", "stt", name="uq_council_decision_row_stt"),
        UniqueConstraint(
            "decision_id", "set_row_id", name="uq_council_decision_row_u5"
        ),
        Index(
            "uq_council_decision_row_u3_ho_so",
            "profile_id",
            unique=True,
            postgresql_where=text(DIEU_KIEN_DONG_HIEU_LUC),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trang_thai_cha: Mapped[str] = mapped_column(String(16), nullable=False)
    set_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    set_row_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    stt: Mapped[int] = mapped_column(Integer, nullable=False)
    bi_bo_boi_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("council_decision.id"), nullable=True, index=True
    )


class CouncilDecisionScan(Base):
    """Bản scan (PDF) của tờ giấy đã ký — bytes deferred; sha + kích thước khớp nội dung."""

    __tablename__ = "council_decision_scan"
    __table_args__ = (
        CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_decision_scan_sha256_noi_dung"
        ),
        CheckConstraint(CHECK_KICH_THUOC, name="ck_council_decision_scan_kich_thuoc"),
        CheckConstraint(CHECK_SCAN_KIEU, name="ck_council_decision_scan_kieu"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("council_decision.id"),
        nullable=False,
        unique=True,
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kich_thuoc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kieu: Mapped[str] = mapped_column(String(64), nullable=False)
    noi_dung: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)


class CouncilDecisionHold(Base):
    """Nhóm "chờ Admin quyết" (F244, owner C7): em có tên trong văn bản bị huỷ hiệu lực không tự
    trở lại diện xét — Admin cho phép TỪNG em. Một em ≤ một mục ``cho_quyet`` (H1)."""

    __tablename__ = "council_decision_hold"
    __table_args__ = (
        CheckConstraint(CHECK_CHO_LY_DO_VAO, name="ck_council_decision_hold_ly_do_vao"),
        CheckConstraint(
            CHECK_CHO_TRANG_THAI, name="ck_council_decision_hold_trang_thai"
        ),
        CheckConstraint(CHECK_CHO_H3, name="ck_council_decision_hold_h3"),
        CheckConstraint(CHECK_CHO_H4_XL, name="ck_council_decision_hold_h4_xl"),
        CheckConstraint(CHECK_CHO_H4_CQ, name="ck_council_decision_hold_h4_cq"),
        CheckConstraint(CHECK_CHO_H4_VH, name="ck_council_decision_hold_h4_vh"),
        CheckConstraint(CHECK_CHO_LY_DO, name="ck_council_decision_hold_ly_do"),
        UniqueConstraint(
            "van_ban_huy_id", "profile_id", name="uq_council_decision_hold_h2"
        ),
        Index(
            "uq_council_decision_hold_h1_cho",
            "profile_id",
            unique=True,
            postgresql_where=text(DIEU_KIEN_H1),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_row_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("council_decision_row.id"), nullable=False
    )
    van_ban_huy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("council_decision.id"), nullable=False, index=True
    )
    ly_do_vao: Mapped[str] = mapped_column(String(32), nullable=False)
    trang_thai: Mapped[str] = mapped_column(String(16), nullable=False)
    tao_luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    quyet_boi_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quyet_luc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ly_do_quyet: Mapped[Optional[str]] = mapped_column(
        String(LY_DO_XOA_TOI_DA), nullable=True
    )
    vo_hieu_boi_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vo_hieu_luc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CouncilDocumentEvent(Base):
    """Nhật ký sự kiện ĐỘC LẬP của bộ văn bản / văn bản đã ký (không khoá ngoại nào — khuôn
    ``council_document_set_deletion``). ``so_lieu`` chỉ id + số đếm + số dòng; không CCCD, không
    lý do, không ảnh chụp. Ghi CÙNG giao dịch với thao tác."""

    __tablename__ = "council_document_event"
    __table_args__ = (
        CheckConstraint(CHECK_SU_KIEN_LOAI, name="ck_council_document_event_loai"),
        CheckConstraint(
            CHECK_SU_KIEN_SO_LIEU, name="ck_council_document_event_so_lieu"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loai: Mapped[str] = mapped_column(String(32), nullable=False)
    set_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    decision_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    hold_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nguoi_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    luc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    so_lieu: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
