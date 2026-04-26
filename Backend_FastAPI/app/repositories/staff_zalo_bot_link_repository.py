"""Repository for ``staff_zalo_bot_link`` rows.

One row per ``user_id`` (unique). Reactivation of a previously-unlinked
user reuses the existing row and stamps a new ``chat_id`` rather than
inserting — keeping audit trail clean and avoiding accidental duplicate
unique-constraint violations.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff_zalo_bot_link import StaffZaloBotLink


class StaffZaloBotLinkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: int) -> Optional[StaffZaloBotLink]:
        result = await self.db.execute(
            select(StaffZaloBotLink).where(StaffZaloBotLink.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_user_id(self, user_id: int) -> Optional[StaffZaloBotLink]:
        result = await self.db.execute(
            select(StaffZaloBotLink).where(
                StaffZaloBotLink.user_id == user_id,
                StaffZaloBotLink.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_chat_id(self, chat_id: str) -> Optional[StaffZaloBotLink]:
        result = await self.db.execute(
            select(StaffZaloBotLink).where(
                StaffZaloBotLink.chat_id == chat_id,
                StaffZaloBotLink.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create_or_reactivate(
        self,
        user_id: int,
        chat_id: str,
        display_name: Optional[str] = None,
    ) -> StaffZaloBotLink:
        """Reuse existing row for this ``user_id`` — never INSERT a second row."""
        existing = await self.get_by_user_id(user_id)
        if existing:
            existing.chat_id = chat_id
            existing.display_name = display_name
            existing.is_active = True
            await self.db.flush()
            return existing
        link = StaffZaloBotLink(
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            is_active=True,
        )
        self.db.add(link)
        await self.db.flush()
        return link

    async def deactivate_by_user_id(self, user_id: int) -> bool:
        link = await self.get_by_user_id(user_id)
        if not link or not link.is_active:
            return False
        link.is_active = False
        await self.db.flush()
        return True
