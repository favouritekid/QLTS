# app/repositories/admission_review_selection_repository.py
"""GĐ2-C C2 — truy cập dữ liệu THUẦN cho bảng lựa chọn của Ban thư ký (``admission_review_selection``) + hai câu đọc dòng kết quả
của lượt ``evaluate`` mới nhất. Thiết kế GĐ2-C 22-11 §2.2, §3.1.

KHÔNG luật nghiệp vụ: không kiểm ``draft``, không so mã băm, không quyết lỗi — dịch vụ ``admission_review_selection_service`` làm,
theo ĐÚNG thứ tự khoá (lần xét ``FOR UPDATE`` qua ``admission_review_repository.lock_session`` → hồ sơ ``FOR UPDATE`` →
đọc → chèn). Bất biến CSDL do trigger giữ (``app/models/admission_review_selection_ddl.py``) — hàm ở đây không lách được.

"Lựa chọn HIỆU LỰC" của (lần xét, hồ sơ) = dòng cuối chuỗi thay thế: không dòng nào có ``supersedes_id`` trỏ tới nó (MỘT vị từ
:func:`_is_effective` cho mọi câu đọc). "Dòng hiện tại" = dòng của lượt ``evaluate`` ĐÃ XONG mới nhất của lần xét (MỘT câu con
:func:`latest_done_evaluate_run_id_sql`).

Không ``commit`` (router commit). Mỗi bước có thể cần chen / bơm lỗi trong test là MỘT hàm cấp module.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import and_, func, select, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import models
from app.models.admission_review import REVIEW_RUN_DONE, REVIEW_RUN_KIND_EVALUATE
from app.repositories.document_bulk_repository import db_clock  # noqa: F401 — một nguồn đồng hồ CSDL

Sel = models.AdmissionReviewSelection
R = models.AdmissionReviewRun
W = models.AdmissionReviewRow
U = models.User


def latest_done_evaluate_run_id_sql(session_id: int):
    """Câu con vô hướng: ``id`` lượt ``evaluate`` ``done`` MỚI NHẤT của lần xét (NULL nếu chưa có)."""
    return (
        select(func.max(R.id))
        .where(R.session_id == session_id, R.kind == REVIEW_RUN_KIND_EVALUATE, R.status == REVIEW_RUN_DONE)
        .scalar_subquery()
    )


def _is_effective(sel=Sel):
    """Vị từ "dòng này chưa bị thay" — MỘT chỗ."""
    later = aliased(Sel)
    return ~select(later.id).where(later.supersedes_id == sel.id).exists()


async def lock_profile(db: AsyncSession, profile_id: int) -> bool:
    """Hồ sơ ``FOR UPDATE`` (thiết kế GĐ2-C §3.1: "Ghi lựa chọn: lần xét ``FOR UPDATE`` (KHÔNG khoá năm), rồi hồ sơ ``FOR
    UPDATE``"). ``False`` = hồ sơ không còn. Một hồ sơ / lần gọi — thứ tự id tăng của nhiều hồ sơ không áp dụng."""
    return (
        await db.execute(text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": int(profile_id)})
    ).scalar_one_or_none() is not None


async def latest_done_evaluate_run_id(db: AsyncSession, session_id: int) -> Optional[int]:
    return (await db.execute(select(latest_done_evaluate_run_id_sql(session_id)))).scalar_one_or_none()


async def get_row(db: AsyncSession, run_id: int, profile_id: int) -> Optional[Row]:
    """Dòng kết quả (lượt, hồ sơ) — cột cần cho lựa chọn: ``row_hash``, ``considered_choice_id``, ``tab``, ``flags``."""
    return (
        await db.execute(
            select(W.row_hash, W.considered_choice_id, W.tab, W.flags).where(
                W.run_id == run_id, W.profile_id == profile_id
            )
        )
    ).one_or_none()


async def effective_selection(db: AsyncSession, session_id: int, profile_id: int) -> Optional[models.AdmissionReviewSelection]:
    """Lựa chọn hiệu lực của (lần xét, hồ sơ) — đọc thường. Người gọi đã giữ dòng lần xét ``FOR UPDATE`` (mọi đường ghi lựa
    chọn lấy cùng khoá ⇒ không ai chèn chen giữa lúc đọc và lúc ghi). ``limit(2)`` + ``scalar_one_or_none``: hai dòng "hiệu lực"
    (chuỗi thay thế rẽ nhánh — CSDL đã chặn bằng UNIQUE) ⇒ ném lỗi, không chọn bừa một dòng."""
    return (
        await db.execute(
            select(Sel).where(Sel.session_id == session_id, Sel.profile_id == profile_id, _is_effective()).limit(2)
        )
    ).scalar_one_or_none()


async def insert_selection(db: AsyncSession, values: dict) -> models.AdmissionReviewSelection:
    sel = Sel(**values)
    db.add(sel)
    await db.flush()
    return sel


def _with_people_and_current_row(q, session_id: int):
    """Gắn người ghi (tên đăng nhập, họ tên — CÁN BỘ, không dữ liệu học sinh) và ``row_hash`` của dòng hiện tại."""
    latest = latest_done_evaluate_run_id_sql(session_id)
    return q.outerjoin(W, and_(W.run_id == latest, W.profile_id == Sel.profile_id)).join(
        U, U.id == Sel.decided_by_user_id
    )


async def list_effective_selections(db: AsyncSession, session_id: int) -> List[Row]:
    """Mọi lựa chọn HIỆU LỰC của lần xét (một dòng / hồ sơ), sắp ``profile_id`` tăng. Mỗi hàng: (lựa chọn, ``row_hash`` của dòng
    hiện tại hoặc NULL, tên đăng nhập, họ tên người ghi)."""
    q = select(Sel, W.row_hash, U.username, U.full_name)
    q = _with_people_and_current_row(q, session_id).where(Sel.session_id == session_id, _is_effective())
    return list((await db.execute(q.order_by(Sel.profile_id))).all())


async def selection_history(db: AsyncSession, session_id: int, profile_id: int) -> List[Row]:
    """MỌI lựa chọn của (lần xét, hồ sơ), MỚI trước (id giảm). Mỗi hàng: (lựa chọn, ``row_hash`` dòng hiện tại, tên đăng nhập,
    họ tên người ghi)."""
    q = select(Sel, W.row_hash, U.username, U.full_name)
    q = _with_people_and_current_row(q, session_id).where(Sel.session_id == session_id, Sel.profile_id == profile_id)
    return list((await db.execute(q.order_by(Sel.id.desc()))).all())


async def user_summary(db: AsyncSession, user_id: int) -> Optional[Row]:
    return (await db.execute(select(U.username, U.full_name).where(U.id == user_id))).one_or_none()


async def rows_with_flags_and_effective_selection(
    db: AsyncSession, session_id: int, flags: Sequence[str]
) -> List[Row]:
    """MỘT câu: các dòng của lượt ``evaluate`` mới nhất mang ÍT NHẤT một cờ trong ``flags`` + lựa chọn HIỆU LỰC (nếu có) của hồ
    sơ ấy. Mỗi hàng: ``profile_id``, ``flags``, ``row_hash``, ``selection_id``, ``selection_kind``, ``selection_row_hash``.
    Chưa có lượt xong ⇒ rỗng. Sắp ``profile_id`` tăng."""
    latest = latest_done_evaluate_run_id_sql(session_id)
    q = (
        select(
            W.profile_id,
            W.flags,
            W.row_hash,
            Sel.id.label("selection_id"),
            Sel.kind.label("selection_kind"),
            Sel.based_on_row_hash.label("selection_row_hash"),
        )
        .select_from(W)
        .outerjoin(Sel, and_(Sel.session_id == session_id, Sel.profile_id == W.profile_id, _is_effective()))
        .where(W.run_id == latest, W.flags.overlap(list(flags)))
        .order_by(W.profile_id)
    )
    return list((await db.execute(q)).all())


async def session_exists(db: AsyncSession, session_id: int) -> bool:
    return (
        await db.execute(select(models.AdmissionReviewSession.id).where(models.AdmissionReviewSession.id == session_id))
    ).scalar_one_or_none() is not None
