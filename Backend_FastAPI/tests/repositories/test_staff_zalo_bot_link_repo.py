"""Repository happy-path tests for ``StaffZaloBotLinkRepository``.

The schema is created via ``Base.metadata.create_all()`` in the test
fixture, so registering ``StaffZaloBotLink`` in ``app.models.__init__``
is enough — no migration required for these tests.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.staff_zalo_bot_link_repository import (
    StaffZaloBotLinkRepository,
)


@pytest.mark.integration
class TestStaffZaloBotLinkRepository:
    @pytest.mark.asyncio
    async def test_create_then_lookup_by_user_and_chat(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        repo = StaffZaloBotLinkRepository(db)

        link = await repo.create_or_reactivate(
            user_id=user_id, chat_id="chat_alpha", display_name="Officer A"
        )
        await db.commit()

        assert link.id is not None
        assert link.is_active is True
        assert link.chat_id == "chat_alpha"

        by_user = await repo.get_active_by_user_id(user_id)
        assert by_user is not None and by_user.id == link.id

        by_chat = await repo.get_active_by_chat_id("chat_alpha")
        assert by_chat is not None and by_chat.id == link.id

    @pytest.mark.asyncio
    async def test_create_or_reactivate_reuses_row(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """Second call must NOT INSERT a second row — same row, fresh chat_id."""
        user_id = officer_user_in_db["id"]
        repo = StaffZaloBotLinkRepository(db)

        first = await repo.create_or_reactivate(user_id, "chat_first", "Name")
        await db.commit()
        first_id = first.id

        # Simulate user re-linking with a different phone/chat_id
        second = await repo.create_or_reactivate(user_id, "chat_second", "Name 2")
        await db.commit()

        assert second.id == first_id, "user_id is unique — must reuse the row"
        assert second.chat_id == "chat_second"
        assert second.display_name == "Name 2"
        assert second.is_active is True

    @pytest.mark.asyncio
    async def test_deactivate_then_reactivate(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        repo = StaffZaloBotLinkRepository(db)

        await repo.create_or_reactivate(user_id, "chat_x", None)
        await db.commit()

        ok = await repo.deactivate_by_user_id(user_id)
        await db.commit()
        assert ok is True

        # Calling deactivate twice is a no-op (row already inactive).
        ok_again = await repo.deactivate_by_user_id(user_id)
        assert ok_again is False, "must only return True on a state transition"

        # Inactive row is hidden from the active-only finder.
        assert await repo.get_active_by_user_id(user_id) is None

        # Re-link reuses the same row and flips is_active back on.
        revived = await repo.create_or_reactivate(user_id, "chat_y", "Display")
        await db.commit()
        assert revived.is_active is True
        assert revived.chat_id == "chat_y"
