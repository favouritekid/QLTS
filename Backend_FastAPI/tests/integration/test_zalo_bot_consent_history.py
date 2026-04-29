"""Consent history parity for Zalo Bot link/unlink/displacement.

PR-Sec-1 (Task 5). Mirrors PR-Audit-1 but for ``notification_consent``
+ ``notification_consent_history`` rows. Locks in:
- Successful link writes a ``zalo_bot`` consent row with status=granted
  and appends a history row.
- Unlink (REST + webhook) flips the consent row to revoked and appends
  another history row, with ``consent_source`` distinguishing the
  trigger (``unlink:api`` vs ``unlink:zalo_bot_webhook``).
- Displacement revokes consent for the displaced user (separate row
  keyed by their user_id) without touching the new user's grant.
- Failures inside ``record_zalo_bot_consent`` MUST NOT block the link
  operation — link table remains source of truth.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_consent import NotificationConsent
from app.models.notification_consent_history import NotificationConsentHistory
from app.services import zalo_bot_link_service


pytestmark = pytest.mark.integration


async def _consent_row(
    db: AsyncSession, user_id: int
) -> NotificationConsent | None:
    q = select(NotificationConsent).where(
        NotificationConsent.channel == "zalo_bot",
        NotificationConsent.source_type == "user",
        NotificationConsent.source_id == user_id,
    )
    return (await db.execute(q)).scalars().first()


async def _history_rows(
    db: AsyncSession, user_id: int
) -> list[NotificationConsentHistory]:
    q = (
        select(NotificationConsentHistory)
        .where(
            NotificationConsentHistory.channel == "zalo_bot",
            NotificationConsentHistory.source_type == "user",
            NotificationConsentHistory.source_id == user_id,
        )
        .order_by(NotificationConsentHistory.id)
    )
    return list((await db.execute(q)).scalars().all())


class TestLinkWritesGrantedConsent:
    @pytest.mark.asyncio
    async def test_first_link_writes_granted_consent_and_history(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            ok, _, _ = await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_consent_link", "Officer A"
            )
        assert ok is True
        await db.commit()

        consent = await _consent_row(db, user_id)
        assert consent is not None
        assert consent.consent_status == "granted"
        assert consent.consent_source == "link"

        history = await _history_rows(db, user_id)
        assert len(history) == 1
        assert history[0].action == "granted"
        assert history[0].new_status == "granted"
        assert history[0].old_status is None  # First write — no prior state.


class TestUnlinkRevokesConsent:
    @pytest.mark.asyncio
    async def test_rest_unlink_revokes_with_api_source(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_unlink_consent", None
            )
            await db.commit()

        ok, _, _ = await zalo_bot_link_service.unlink(db, user_id)
        assert ok is True
        await db.commit()

        consent = await _consent_row(db, user_id)
        assert consent is not None
        assert consent.consent_status == "revoked"
        assert consent.consent_source == "unlink:api"

        history = await _history_rows(db, user_id)
        # Two events: granted (link) → revoked (unlink).
        actions = [h.action for h in history]
        assert actions == ["granted", "revoked"]
        assert history[1].old_status == "granted"
        assert history[1].new_status == "revoked"

    @pytest.mark.asyncio
    async def test_webhook_unlink_revokes_with_webhook_source(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_unlink_wh_consent", None
            )
            await db.commit()

        ok, _, _ = await zalo_bot_link_service.unlink_by_chat_id(
            db, "chat_unlink_wh_consent"
        )
        assert ok is True
        await db.commit()

        consent = await _consent_row(db, user_id)
        assert consent.consent_status == "revoked"
        assert consent.consent_source == "unlink:zalo_bot_webhook"


class TestDisplacementRevokesDisplacedUser:
    @pytest.mark.asyncio
    async def test_displaced_user_consent_flipped_to_revoked(
        self,
        db: AsyncSession,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
    ):
        user_a = officer_user_in_db["id"]
        user_b = manager_user_in_db["id"]

        # User A links chat_X first.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_a)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_displaced", None
            )
            await db.commit()

        # User B displaces A by linking the same chat_X.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_b)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "DEF456", "chat_displaced", None
            )
            await db.commit()

        # A's consent should be revoked with source=displaced.
        consent_a = await _consent_row(db, user_a)
        assert consent_a is not None
        assert consent_a.consent_status == "revoked"
        assert consent_a.consent_source == "displaced"

        # B's consent should be granted (the displacement does not touch
        # the new user's row — only the displaced one).
        consent_b = await _consent_row(db, user_b)
        assert consent_b is not None
        assert consent_b.consent_status == "granted"
        assert consent_b.consent_source == "link"

        # A's timeline: granted (initial link) → revoked (displacement).
        history_a = await _history_rows(db, user_a)
        actions_a = [h.action for h in history_a]
        assert actions_a == ["granted", "revoked"]


class TestConsentFailureDoesNotBlockLink:
    """Verifies the M2 contract: ``record_zalo_bot_consent`` re-raises;
    caller wraps SAVEPOINT + try/except so the savepoint rollback path
    runs cleanly (no PendingRollbackError) and the outer link
    transaction survives.
    """

    @pytest.mark.asyncio
    async def test_link_succeeds_when_consent_upsert_raises_runtime(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """RuntimeError variant — exercises the "non-flush failure" path
        (e.g. transient logic error before any SQL is sent). The
        SAVEPOINT __aexit__ rolls back, caller's except logs, link
        commits.
        """
        user_id = officer_user_in_db["id"]

        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ), patch(
            "app.services.notification_consent_service.upsert_consent",
            new=AsyncMock(side_effect=RuntimeError("simulated transient")),
        ):
            ok, _, _ = await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_link_consent_fail_rt", None
            )
        assert ok is True, "link must commit even when consent insert raises"
        await db.commit()

        from app.repositories.staff_zalo_bot_link_repository import (
            StaffZaloBotLinkRepository,
        )

        repo = StaffZaloBotLinkRepository(db)
        link = await repo.get_active_by_chat_id("chat_link_consent_fail_rt")
        assert link is not None
        assert link.user_id == user_id

    @pytest.mark.asyncio
    async def test_link_succeeds_when_consent_upsert_raises_integrity(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """IntegrityError variant — exercises the realistic path: the
        upsert flushes, the DB returns a constraint error, and the
        SAVEPOINT must clean up the poisoned session state before the
        outer transaction tries to commit. Without proper SAVEPOINT
        isolation this would manifest as PendingRollbackError on
        ``db.commit()`` and the link write would be silently lost.
        """
        from sqlalchemy.exc import IntegrityError

        user_id = officer_user_in_db["id"]

        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ), patch(
            "app.services.notification_consent_service.upsert_consent",
            new=AsyncMock(
                side_effect=IntegrityError(
                    "INSERT", {}, Exception("simulated unique violation")
                )
            ),
        ):
            ok, _, _ = await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_link_consent_fail_ie", None
            )
        assert ok is True, "link must survive consent IntegrityError"
        # CRITICAL: outer commit must NOT raise PendingRollbackError —
        # if it does, the SAVEPOINT contract is broken.
        await db.commit()

        from app.repositories.staff_zalo_bot_link_repository import (
            StaffZaloBotLinkRepository,
        )

        repo = StaffZaloBotLinkRepository(db)
        link = await repo.get_active_by_chat_id("chat_link_consent_fail_ie")
        assert link is not None
        assert link.user_id == user_id
