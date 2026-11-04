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
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

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
    bền TRƯỚC khi trả bytes. ``set_id`` KHÔNG là khoá ngoại: xoá bộ không làm mất nhật ký."""

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
