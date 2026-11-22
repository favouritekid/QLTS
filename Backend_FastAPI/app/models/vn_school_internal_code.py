# app/models/vn_school_internal_code.py
"""MỘT nguồn cho mã nội bộ trường THCS (``NB`` + 6 số) — owner 22-11, đề xuất danh mục THCS Phần A1.

Đặt trong ``app/models`` (cùng khuôn ``admission_quota_ddl.py``): model ``vn_school`` dùng chuỗi vị từ cho CHECK /
chỉ mục, service và các script nạp danh mục Bộ dùng hàm Python — một module nhẹ, chỉ phụ thuộc SQLAlchemy.

Vì sao có mã nội bộ
===================

``vn_school.moet_school_code`` + ``moet_province_code`` bắt buộc, và cặp ấy còn là khoá đối chiếu khi nạp danh mục
của Bộ năm sau. Trường THCS KHÔNG có mã Bộ (danh mục Bộ chỉ có trường THPT). Nếu Admin tự gõ một mã số cho trường
THCS, một lần nạp danh mục Bộ về sau có thể khớp nhầm mã ấy rồi ghi đè tên / cấp / KV của trường THCS.

Quy ước: trường nội bộ mang mã ``NB`` + 6 số (``NB000123``), do MÁY sinh từ sequence
``vn_school_internal_code_seq``. Mã Bộ là số ⇒ không bao giờ trùng. Tiền tố ``NB`` (mọi kiểu chữ, sau khi bỏ khoảng
trắng đầu/cuối) là VÙNG DÀNH RIÊNG:

* Admin không gõ tay được mã ``NB…`` (``vn_school_service``);
* mọi bộ nạp danh mục Bộ bỏ qua dòng nguồn mang mã ``NB…`` và KHÔNG BAO GIỜ khớp / sửa / xoá một trường ``NB…``
  (``import_schools_csv``, ``app/scripts/import_moet_schools_3_provinces.py``,
  ``app/scripts/rebuild_school_kv_from_xls.py``, ``app/scripts/dedup_temporal_split.py``).

Hai dạng của cùng một vị từ
===========================

* Python: :func:`is_internal_school_code`.
* SQL: :func:`internal_code_sql` / :func:`not_internal_code_sql` — biểu thức ``upper(btrim(col)) LIKE 'NB%'``.

Hai dạng PHẢI cho cùng kết quả; ``tests/unit/test_vn_school_thcs_noi_bo.py`` so chúng trên CSDL thật. CHECK
``ck_vn_school_internal_code_format`` và chỉ mục duy nhất ``uq_vn_school_internal_code`` (model + migration
``thcsnb20261122``) dùng ĐÚNG chuỗi :data:`INTERNAL_CODE_SQL_PREDICATE`.

Tầng chủ sở hữu bất biến "trường THCS dùng mã NB do máy sinh, có mã xã còn hiệu lực" = ``VnSchoolService``
(``create_school`` / ``update_school`` / ``import_schools_csv``). CHECK + chỉ mục duy nhất ở CSDL là lớp phòng thủ thêm.
"""
from __future__ import annotations

import re
from typing import Any, Final

from sqlalchemy import func, not_

INTERNAL_SCHOOL_CODE_PREFIX: Final[str] = "NB"
INTERNAL_SCHOOL_CODE_DIGITS: Final[int] = 6
INTERNAL_SCHOOL_CODE_MAX: Final[int] = 10**INTERNAL_SCHOOL_CODE_DIGITS - 1
INTERNAL_SCHOOL_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^NB[0-9]{6}$")
INTERNAL_CODE_SEQUENCE_NAME: Final[str] = "vn_school_internal_code_seq"

#: Cấp trường được cấp mã nội bộ. ``THCS`` LUÔN mã nội bộ (không có mã Bộ). ``THCS_THPT`` (liên cấp): bỏ trống mã ⇒
#: mã nội bộ; gõ mã ⇒ đó là mã Bộ (trường liên cấp có cấp THPT nằm trong danh mục Bộ).
INTERNAL_CODE_LEVELS: Final[frozenset[str]] = frozenset({"THCS", "THCS_THPT"})
#: Cấp KHÔNG BAO GIỜ mang mã Bộ — gõ mã cho cấp này bị từ chối.
NO_MOET_CODE_LEVELS: Final[frozenset[str]] = frozenset({"THCS"})

#: Nguồn của dòng KV chép từ KV hiện hành của xã (owner câu 2: "chép từ xã + câu kiểm lệch"). DÀNH RIÊNG cho đường
#: xác nhận KV gợi ý — đường thêm / sửa KV chung không được ghi nguồn này.
KV_SOURCE_COMMUNE_CURRENT: Final[str] = "xa_hien_hanh"
#: Năm bắt đầu hiệu lực của dòng KV chép từ xã — owner 22-11 (``QUYET-DINH-OWNER-L3A-5-CAU-2026-11-22.md`` câu 2):
#: "Từ năm 2000, phủ mọi hồ sơ" — máy tự điền, không có năm kết thúc, Admin không nhập năm.
KV_COMMUNE_EFFECTIVE_FROM_YEAR: Final[int] = 2000

#: Vị từ SQL (chuỗi) dùng trong CHECK / chỉ mục — tham số hoá theo tên cột.
INTERNAL_CODE_SQL_PREDICATE: Final[str] = "upper(btrim({col})) LIKE 'NB%'"


def is_internal_school_code(code: Any) -> bool:
    """Mã thuộc vùng dành riêng ``NB…`` không (mọi kiểu chữ, bỏ khoảng trắng đầu/cuối)."""
    return isinstance(code, str) and code.strip().upper().startswith(INTERNAL_SCHOOL_CODE_PREFIX)


def format_internal_school_code(number: int) -> str:
    """Số thứ tự từ sequence ⇒ ``NB`` + 6 số. Ngoài [1, 999999] ⇒ ``ValueError`` (fail-closed, không cắt / quay vòng)."""
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"Số thứ tự mã nội bộ phải là số nguyên, nhận {number!r}")
    if number < 1 or number > INTERNAL_SCHOOL_CODE_MAX:
        raise ValueError(
            f"Số thứ tự mã nội bộ {number} ngoài khoảng 1..{INTERNAL_SCHOOL_CODE_MAX}"
        )
    return f"{INTERNAL_SCHOOL_CODE_PREFIX}{number:0{INTERNAL_SCHOOL_CODE_DIGITS}d}"


def internal_code_sql(column: Any) -> Any:
    """Biểu thức SQLAlchemy: cột mã thuộc vùng ``NB…`` — cùng nghĩa :func:`is_internal_school_code`."""
    return func.upper(func.btrim(column)).like(f"{INTERNAL_SCHOOL_CODE_PREFIX}%")


def not_internal_code_sql(column: Any) -> Any:
    """Biểu thức SQLAlchemy: cột mã KHÔNG thuộc vùng ``NB…`` — bộ lọc bắt buộc của mọi bộ nạp danh mục Bộ."""
    return not_(internal_code_sql(column))
