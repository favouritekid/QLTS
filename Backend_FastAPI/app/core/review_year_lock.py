"""GĐ2 — KHOÁ NĂM (``advisory_lock_keys.REVIEW_YEAR_NS``): MỘT định nghĩa cho mọi nơi lấy khoá này.

BẤT BIẾN (GĐ2-F1 lượt 3 — điểm chặn Codex lượt 2): mọi lệnh ghi làm đổi tập ``(offering_academic_info.id,
annual_admission_quota)`` của học vụ một năm PHẢI giữ khoá năm của MỌI năm bị chạm (id năm tăng dần) TRƯỚC khi chạm dòng học vụ:

* tạo học vụ — ``organization_service.create_academic_info`` (dòng mới đổi tập dòng kể cả khi chỉ tiêu trống);
* sửa chỉ tiêu / dời năm học vụ — ``organization_service.update_academic_info`` (năm cũ + năm mới);
* bảng chỉ tiêu năm — ``admission_quota_table_service`` (PUT / khoá / mở khoá; GĐ2-C: khoá lần xét).

Hệ quả: dấu chỉ tiêu (``admission_quota_table_service.quota_fingerprint_of``) đọc SAU khoá năm không thể bị một lệnh tạo / sửa /
dời CHƯA commit làm sai — lệnh ấy hoặc đã commit xong trước (ta thấy giá trị mới), hoặc phải chờ ta commit (giá trị của họ nằm SAU).

Không đường nào được khoá dòng học vụ TRƯỚC rồi mới lấy khoá năm (sẽ tạo vòng chờ với đường tạo / sửa / PUT): các nơi gọi đều lấy
khoá năm ngay sau kiểm quyền, khi giao dịch chưa giữ khoá dòng học vụ nào. Xoá mềm (``is_deleted``, kể cả dây chuyền khi xoá
offering) không đổi ``(id, chỉ tiêu)`` ⇒ không cần khoá năm.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .advisory_lock_keys import REVIEW_YEAR_NS


async def lock_review_year(db: AsyncSession, academic_year: int) -> None:
    """Khoá năm — khoá GIAO DỊCH ``pg_advisory_xact_lock(REVIEW_YEAR_NS, năm)``, nhả khi commit / rollback."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": REVIEW_YEAR_NS, "k": int(academic_year)}
    )


async def lock_review_years(db: AsyncSession, academic_years: Iterable[Optional[int]]) -> None:
    """Khoá nhiều năm theo thứ tự TĂNG DẦN, mỗi năm một lần (vd dời học vụ giữa hai năm) ⇒ hai giao dịch chạm cùng cặp năm
    không vòng chờ nhau."""
    for nam in sorted({int(y) for y in academic_years if y is not None}):
        await lock_review_year(db, nam)
