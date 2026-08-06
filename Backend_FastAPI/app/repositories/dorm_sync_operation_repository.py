"""Truy cập sổ cái ``dorm_sync_operations``.

🔴 Điểm cốt lõi của file này là :func:`chen_neu_chua_co`. Hai request apply đến
cùng lúc với cùng ``operation_id`` là ca có thật (người dùng bấm hai lần, hoặc
trình duyệt retry), và cách xử lý sai ở đây biến một cú bấm nhầm thành hai lượt
hạ cờ.

Dùng ``INSERT … ON CONFLICT DO NOTHING RETURNING`` chứ **không** bắt
``IntegrityError``: unique violation có thể nổ ngay tại ``flush()`` bên trong
service, và khi đó nó đã thoát ra thành 500 trước khi ai kịp bắt. Với
``ON CONFLICT`` thì bên thua đơn giản là **không nhận được hàng nào** — một kết
quả bình thường, đọc lại hàng của bên thắng rồi xử theo trạng thái.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dorm_sync_operation import DormSyncOperation


async def lay_theo_operation_id(
    db: AsyncSession, operation_id: uuid.UUID
) -> Optional[DormSyncOperation]:
    """Đọc sổ theo ``operation_id``. ``None`` nghĩa là lượt này chưa từng chạy."""
    ket_qua = await db.execute(
        select(DormSyncOperation).where(
            DormSyncOperation.operation_id == operation_id
        )
    )
    return ket_qua.scalar_one_or_none()


async def chen_neu_chua_co(
    db: AsyncSession,
    *,
    operation_id: uuid.UUID,
    actor_id: int,
    academic_year: int,
    snapshot_hash: str,
    snapshot_version: int,
) -> Optional[DormSyncOperation]:
    """Chèn hàng ``running``; trả ``None`` nếu ``operation_id`` đã tồn tại.

    ``None`` ở đây **không phải lỗi** — nó nghĩa là một request khác đã thắng
    cuộc đua. Người gọi phải đọc lại hàng của bên thắng bằng
    :func:`lay_theo_operation_id` và xử theo trạng thái của nó.

    ⚠️ Chỉ ``flush``, không ``commit``: router mới là nơi commit (kiến trúc V3.0).
    """
    cau_lenh = (
        pg_insert(DormSyncOperation)
        .values(
            operation_id=operation_id,
            actor_id=actor_id,
            academic_year=academic_year,
            snapshot_hash=snapshot_hash,
            snapshot_version=snapshot_version,
            status="running",
        )
        .on_conflict_do_nothing(index_elements=["operation_id"])
        .returning(DormSyncOperation)
    )

    ket_qua = await db.execute(cau_lenh)
    hang = ket_qua.scalar_one_or_none()
    if hang is not None:
        await db.flush()
    return hang


async def cap_nhat_ket_qua(
    db: AsyncSession,
    so_cai: DormSyncOperation,
    *,
    status: str,
    ktx_run_id: Optional[int] = None,
    result: Optional[Dict[str, Any]] = None,
) -> DormSyncOperation:
    """Ghi kết quả lượt chạy vào sổ. Chỉ ``flush`` — router commit."""
    so_cai.status = status
    if ktx_run_id is not None:
        so_cai.ktx_run_id = ktx_run_id
    if result is not None:
        so_cai.result = result
    await db.flush()
    return so_cai
