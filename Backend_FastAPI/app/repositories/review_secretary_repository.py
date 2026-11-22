# app/repositories/review_secretary_repository.py
"""GĐ2-C C1 — truy cập dữ liệu bảng quyền "Thư ký Hội đồng" (``admission_review_secretary_grant``).

Thứ tự khoá (toàn cục, cùng chiều GĐ1b / K4): dòng ``user`` (``user_deletion_policy.lock_users_in_id_order``, id tăng) →
dòng quyền. Không hàm nào ở đây khoá dòng ``user``.

Đồng hồ: MỘT nguồn ``document_bulk_repository.db_clock`` (``clock_timestamp()``).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.document_bulk_repository import db_clock  # noqa: F401 — một nguồn đồng hồ CSDL

G = models.AdmissionReviewSecretaryGrant

#: Trần số dòng một lần liệt kê (khuôn ``document_bulk_repository.list_grants``).
LIST_LIMIT = 500


async def lock_active_grant_share(db: AsyncSession, user_id: int) -> Optional[models.AdmissionReviewSecretaryGrant]:
    """Quyền CÒN HIỆU LỰC của ``user_id`` — ``FOR SHARE`` TRONG giao dịch của người gọi (``deps.require_review_secretary``).

    Giữ tới hết giao dịch ⇒ Admin thu hồi tay / tự thu hồi (cả hai khoá dòng quyền ``FOR UPDATE``) phải CHỜ lần bấm đang
    ghi commit xong; ngược lại thu hồi đang giữ khoá thì câu này CHỜ, rồi PostgreSQL xét lại ``revoked_at IS NULL`` trên
    bản dòng mới ⇒ không còn dòng ⇒ ``None`` (thiết kế GĐ2-C §4, T17). ``populate_existing``: đọc lại giá trị DƯỚI khoá,
    người gọi kiểm lại ``revoked_at`` (không tin bản nạp trước)."""
    return (
        await db.execute(
            select(G)
            .where(G.user_id == user_id, G.revoked_at.is_(None))
            .order_by(G.id)
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def active_grant_for_user(db: AsyncSession, user_id: int) -> Optional[models.AdmissionReviewSecretaryGrant]:
    """Quyền còn hiệu lực của một người — đọc thường. Người gọi đã giữ dòng ``user`` ấy ``FOR NO KEY UPDATE`` (mọi đường
    gán / tự thu hồi lấy cùng khoá ⇒ không ai chen giữa lúc đọc và lúc ghi)."""
    return (
        await db.execute(
            select(G).where(G.user_id == user_id, G.revoked_at.is_(None)).order_by(G.id).limit(1)
        )
    ).scalar_one_or_none()


async def lock_active_grants_of_user_for_update(
    db: AsyncSession, user_id: int
) -> List[models.AdmissionReviewSecretaryGrant]:
    """Mọi quyền CHƯA thu hồi của một người — ``FOR UPDATE`` theo id TĂNG (tự thu hồi khi khoá / đổi vai tài khoản).
    Quyền không có hạn (owner C1) ⇒ không lọc theo đồng hồ."""
    return list(
        (
            await db.execute(
                select(G)
                .where(G.user_id == user_id, G.revoked_at.is_(None))
                .order_by(G.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def lock_grant_for_update(db: AsyncSession, grant_id: int) -> Optional[models.AdmissionReviewSecretaryGrant]:
    return (
        await db.execute(
            select(G).where(G.id == grant_id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def list_grants(
    db: AsyncSession, *, active: Optional[bool], user_id: Optional[int]
) -> List[Tuple[models.AdmissionReviewSecretaryGrant, Optional[Any]]]:
    """Mới nhất trước (``id`` giảm), tối đa :data:`LIST_LIMIT` dòng. Mỗi dòng kèm hàng tóm tắt người được gán
    ``(id, username, full_name, role, status)`` — ``None`` nếu không đọc được (không thể xảy ra khi khoá ngoại RESTRICT)."""
    u = models.User
    q = select(G, u.id, u.username, u.full_name, u.role, u.status).join(u, u.id == G.user_id, isouter=True)
    if active is True:
        q = q.where(G.revoked_at.is_(None))
    elif active is False:
        q = q.where(G.revoked_at.is_not(None))
    if user_id is not None:
        q = q.where(G.user_id == user_id)
    rows = (await db.execute(q.order_by(G.id.desc()).limit(LIST_LIMIT))).all()
    return [(r[0], r[1:] if r[1] is not None else None) for r in rows]


async def user_summary(db: AsyncSession, user_id: int) -> Optional[Any]:
    """Hàng ``(id, username, full_name, role, status)`` của một người — đọc thường (dựng phản hồi)."""
    u = models.User
    return (
        await db.execute(select(u.id, u.username, u.full_name, u.role, u.status).where(u.id == user_id))
    ).first()
