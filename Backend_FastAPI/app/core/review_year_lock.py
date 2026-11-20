"""GĐ2 — KHOÁ NĂM (``advisory_lock_keys.REVIEW_YEAR_NS``): MỘT định nghĩa cho mọi nơi lấy khoá này.

BẤT BIẾN (GĐ2-F1 lượt 3 — điểm chặn Codex lượt 2; luật C thêm ``is_deleted``): mọi lệnh ghi làm đổi tập
``(offering_academic_info.id, annual_admission_quota, is_deleted)`` của học vụ một năm PHẢI giữ khoá năm của MỌI năm bị chạm (năm
tăng dần) TRƯỚC khi chạm dòng học vụ:

* tạo học vụ — ``organization_service.create_academic_info`` (dòng mới đổi tập dòng kể cả khi chỉ tiêu trống);
* sửa chỉ tiêu / dời năm học vụ — ``organization_service.update_academic_info`` (năm cũ + năm mới);
* xoá mềm / khôi phục học vụ (luật C, owner 19-11 — cờ ``is_deleted`` nằm trong dấu chỉ tiêu) —
  ``organization_service.delete_academic_info`` / ``restore_academic_info`` và dây chuyền xoá loại hình — ``delete_program_offering``
  và ``delete_major_program`` (owner chốt 20-11: xoá ngành = xoá TỪNG loại hình của ngành, kể cả loại hình đang "Ngừng") qua MỘT
  helper ``_soft_delete_offerings_cascade`` (mọi năm có học vụ của các loại hình, tăng dần);
* bảng chỉ tiêu năm — ``admission_quota_table_service`` (PUT / khoá / mở khoá; GĐ2-C: khoá lần xét).

Hệ quả: dấu chỉ tiêu (``admission_quota_table_service.quota_fingerprint_of``) đọc SAU khoá năm không thể bị một lệnh tạo / sửa /
dời CHƯA commit làm sai — lệnh ấy hoặc đã commit xong trước (ta thấy giá trị mới), hoặc phải chờ ta commit (giá trị của họ nằm SAU).

Không đường nào được khoá dòng học vụ TRƯỚC rồi mới lấy khoá năm (sẽ tạo vòng chờ với đường tạo / sửa / PUT): các nơi gọi đều lấy
khoá năm ngay sau kiểm quyền, khi giao dịch chưa giữ khoá dòng học vụ nào. (Trước luật C, xoá mềm không lấy khoá năm vì không đổi
``(id, chỉ tiêu)``; từ luật C cờ xoá mềm vào dấu và bị chặn khi bảng đã khoá ⇒ lấy khoá năm như sửa chỉ tiêu.)

THỨ TỰ KHOÁ TOÀN HỆ (Codex lượt 3 + lượt 4, owner chốt 20-11): khoá NGÀNH (dòng ``major_program`` ``FOR NO KEY UPDATE`` — chỉ
ở tạo loại hình, bật lại loại hình (ngừng → hoạt động) và xoá ngành, một dòng, ``organization_service._lock_major_program_row``)
→ khoá LOẠI HÌNH (dòng ``program_offering`` ``FOR NO KEY UPDATE`` — chỉ
ở tạo / khôi phục học vụ (``organization_service._lock_offering_row``, một dòng) và dây chuyền xoá loại hình / xoá ngành (mọi dòng
của tập, id TĂNG DẦN, MỘT câu)) → khoá NĂM (tăng dần) → dòng học vụ → dòng bảng chỉ tiêu. Không vòng chờ: (a) đường lấy khoá loại
hình lấy các dòng loại hình TRƯỚC mọi khoá năm, theo id tăng dần trong một câu — chờ dòng loại hình thì chỉ đang giữ dòng loại hình
id NHỎ hơn (mọi đường khác lấy cùng chiều hoặc chỉ một dòng); (b) các đường
chỉ lấy khoá năm (PUT / khoá / mở khoá bảng, sửa / dời / xoá mềm học vụ) không bao giờ chờ dòng loại hình ở chế độ xung đột — chèn /
sửa dòng TRỎ tới loại hình (học vụ, hồ sơ, lead…) chỉ lấy ``FOR KEY SHARE``, không xung đột với ``NO KEY UPDATE``; (c) lệnh UPDATE
dòng loại hình KHÔNG qua khoá năm (ô "Ngừng") không giữ khoá năm / dòng học vụ nào khi chờ ⇒ chờ nó không khép vòng; (d) khoá
ngành luôn lấy khi giao dịch CHƯA giữ khoá loại hình / năm / học vụ nào, và không đường nào giữ khoá loại hình / năm rồi mới chờ
dòng ngành ở chế độ xung đột — chèn loại hình chỉ lấy ``FOR KEY SHARE`` trên ngành (kiểm khoá ngoại), "Ngừng ngành" (UPDATE dòng
ngành) không giữ khoá nào khác khi chờ.

Dây chuyền xoá loại hình / xoá ngành khoá DÒNG học vụ bằng MỘT câu ``FOR NO KEY UPDATE ORDER BY id`` TRƯỚC câu UPDATE (Codex
lượt 3): chỉ ``UPDATE … WHERE offering_id`` thì khoá theo thứ tự QUÉT (vật lý / chỉ mục), có thể ngược chiều id ⇒ vòng chờ ``40P01``
với ghi nhận / Phê duyệt hàng loạt (``quota_occupancy_service.lock_quota_cells``: ``FOR UPDATE`` id tăng dần, KHÔNG lấy khoá năm).

Khoá DÒNG học vụ lấy SAU khoá năm dùng chế độ YẾU NHẤT đủ việc, lấy MỘT lần, không nâng trong cùng giao dịch (GĐ2-F1 lượt 3b):
PUT bảng chỉ tiêu chỉ ghi ``annual_admission_quota`` (không cột nào thuộc khoá duy nhất / khoá ngoại) ⇒ ``FOR NO KEY UPDATE`` —
đúng chế độ lệnh UPDATE của PostgreSQL tự lấy. Nó vẫn xung đột với ``FOR SHARE`` (khoá bảng), ``FOR NO KEY UPDATE`` (UPDATE chỉ
tiêu ở trang cũ / SQL tay) và ``FOR UPDATE`` (``lock_quota_cells`` của ghi nhận / Phê duyệt) ⇒ mọi đường đổi chỉ tiêu vẫn tuần tự;
nhưng KHÔNG xung đột với ``FOR KEY SHARE`` mà kiểm khoá ngoại lấy ⇒ lệnh chèn / sửa dòng TRỎ tới học vụ (học phí, lộ trình xét,
cấu hình, phí…) không phải chờ PUT, và không thể vòng chờ với PUT qua khoá ấy.
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
