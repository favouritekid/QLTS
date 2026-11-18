"""Tiện ích test GĐ1b: phiên bản dòng giấy (``row_version``) để gửi kèm duyệt / từ chối / Đặt lại (đặc tả bản 3.6 §4.7)."""
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


async def phien_ban_giay(profile_id: int, doc_code: str) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument.row_version)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == profile_id, models.ConfigDocumentType.code == doc_code)
            )
        ).scalar_one()
