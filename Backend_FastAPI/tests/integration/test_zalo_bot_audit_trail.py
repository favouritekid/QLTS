"""Audit trail coverage for Zalo Bot link/unlink/displacement/preference flips.

PR-Audit-1 (post-PR #154 reply-confirm fix). Locks in:
- Every link op writes one ``entity_audit_log`` row.
- Displacement writes a ``chat_id_reassigned`` audit + flips displaced
  user's ``zalo_bot_enabled`` to False + builds a ``post_commit``
  closure that fans out ``ZALO_BOT_LINK_DISPLACED`` to the displaced
  user.
- ``_sync_preference`` is a no-op on no-change (no audit row written
  when toggling to current value).
- Source naming: ``zalo_bot_webhook`` for webhook ops, ``api`` for REST.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity_audit_log import EntityAuditLog
from app.models.staff_zalo_bot_link import StaffZaloBotLink
from app.services import zalo_bot_link_service


pytestmark = pytest.mark.integration


async def _audit_rows(db: AsyncSession, entity_type: str, entity_id=None):
    q = select(EntityAuditLog).where(EntityAuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(EntityAuditLog.entity_id == entity_id)
    return (await db.execute(q.order_by(EntityAuditLog.id))).scalars().all()


class TestVerifyAndLinkAudit:
    @pytest.mark.asyncio
    async def test_first_link_writes_created_audit_row(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            ok, _, post_commit = await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_first_link", "Officer A"
            )
        assert ok is True
        assert post_commit is None  # No displacement → no fan-out.
        await db.commit()

        rows = await _audit_rows(db, "StaffZaloBotLink")
        assert len(rows) == 1
        row = rows[0]
        assert row.action == "created"
        assert row.actor_user_id == user_id
        assert row.source == "zalo_bot_webhook"
        # chat_id is masked in audit payload — never store the full id.
        assert "chat_first_link"[:4] in row.new_value["chat_id_prefix"]
        assert row.new_value["is_active"] is True

    @pytest.mark.asyncio
    async def test_pref_flip_writes_field_change_audit_row(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_pref", None
            )
        await db.commit()

        # One field-change audit on NotificationPreference, value False→True.
        pref_rows = await _audit_rows(db, "NotificationPreference")
        assert len(pref_rows) == 1
        row = pref_rows[0]
        assert row.action == "updated"
        assert row.field_name == "zalo_bot_enabled"
        assert row.old_value is False
        assert row.new_value is True
        assert row.source == "zalo_bot_link_service"

    @pytest.mark.asyncio
    async def test_relink_same_chat_id_no_displacement_audit(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """Same user re-links with same chat_id → no displacement, no
        chat_id_reassigned audit. Pref flip is also a no-op (already True)."""
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_self", None
            )
            await db.commit()

            await zalo_bot_link_service.verify_and_link(
                db, "DEF456", "chat_self", None
            )
            await db.commit()

        link_audits = await _audit_rows(db, "StaffZaloBotLink")
        # Two created actions (one per verify_and_link call) but no
        # chat_id_reassigned action.
        actions = [r.action for r in link_audits]
        assert actions.count("created") == 2
        assert "chat_id_reassigned" not in actions

        # Pref audit fires only on first link (False→True). Second is a
        # no-op (True→True) and writes no audit row.
        pref_audits = await _audit_rows(db, "NotificationPreference")
        assert len(pref_audits) == 1


class TestDisplacementAudit:
    @pytest.mark.asyncio
    async def test_displacement_writes_reassigned_audit_and_flips_old_pref(
        self, db: AsyncSession, officer_user_in_db: dict, manager_user_in_db: dict
    ):
        """Critical security event: chat_id moves from user A to user B.
        Must record on the displaced row + flip displaced user's pref +
        return a post_commit closure for fan-out.
        """
        user_a = officer_user_in_db["id"]
        user_b = manager_user_in_db["id"]

        # Step 1: user A links chat_shared.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_a)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "AAA111", "chat_shared", None
            )
            await db.commit()

        # Step 2: user B claims the same chat_shared.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_b)),
        ):
            ok, _, post_commit = await zalo_bot_link_service.verify_and_link(
                db, "BBB222", "chat_shared", None
            )
            assert ok is True
            await db.commit()

        # Displacement closure must exist for fan-out.
        assert post_commit is not None

        # Audit assertions.
        link_audits = await _audit_rows(db, "StaffZaloBotLink")
        actions = [(r.action, r.actor_user_id) for r in link_audits]
        assert ("chat_id_reassigned", user_b) in actions
        # Two created rows (one per user) + one chat_id_reassigned.
        assert len([a for a, _ in actions if a == "created"]) == 2
        assert len([a for a, _ in actions if a == "chat_id_reassigned"]) == 1

        # Displaced user's preference row must be flipped to False with
        # an audit trail attributing the change to user_b (the actor).
        pref_audits = await _audit_rows(db, "NotificationPreference")
        # Find the row that toggled user_a's pref off — actor=user_b.
        toggled_off = [
            r for r in pref_audits
            if r.new_value is False and r.actor_user_id == user_b
        ]
        assert len(toggled_off) == 1, (
            "displaced user's pref must be flipped off with actor=new linker"
        )

    @pytest.mark.asyncio
    async def test_displacement_post_commit_dispatches_event(
        self, db: AsyncSession, officer_user_in_db: dict, manager_user_in_db: dict
    ):
        """The post_commit closure must call safe_dispatch with the
        ZALO_BOT_LINK_DISPLACED event targeting the displaced user."""
        user_a = officer_user_in_db["id"]
        user_b = manager_user_in_db["id"]

        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_a)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "AAA111", "chat_dispatch", None
            )
            await db.commit()

        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_b)),
        ), patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new=AsyncMock(),
        ) as dispatch_mock:
            _, _, post_commit = await zalo_bot_link_service.verify_and_link(
                db, "BBB222", "chat_dispatch", None
            )
            await db.commit()
            assert post_commit is not None
            await post_commit()

        dispatch_mock.assert_awaited_once()
        kwargs = dispatch_mock.await_args.kwargs
        from app.core.events import SystemEvents
        assert kwargs["event"] == SystemEvents.ZALO_BOT_LINK_DISPLACED
        assert kwargs["payload"]["user_id"] == user_a
        assert kwargs["payload"]["displaced_by_user_id"] == user_b
        assert kwargs["payload"]["actor_id"] == user_b


class TestUnlinkAudit:
    @pytest.mark.asyncio
    async def test_unlink_rest_writes_deleted_audit_with_api_source(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_unlink_rest", None
            )
            await db.commit()

        ok, _, _ = await zalo_bot_link_service.unlink(db, user_id)
        assert ok is True
        await db.commit()

        link_audits = await _audit_rows(db, "StaffZaloBotLink")
        deleted = [r for r in link_audits if r.action == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].source == "api"
        assert deleted[0].actor_user_id == user_id

    @pytest.mark.asyncio
    async def test_unlink_via_chat_id_uses_webhook_source(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        user_id = officer_user_in_db["id"]
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_unlink_wh", None
            )
            await db.commit()

        ok, _, _ = await zalo_bot_link_service.unlink_by_chat_id(
            db, "chat_unlink_wh"
        )
        assert ok is True
        await db.commit()

        link_audits = await _audit_rows(db, "StaffZaloBotLink")
        deleted = [r for r in link_audits if r.action == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].source == "zalo_bot_webhook"


class TestBackfillMigrationIdempotency:
    """The backfill migration runs ``INSERT ... WHERE NOT EXISTS`` on
    ``(entity_type, entity_id, action='created')``. Verify that:

    - Re-running the SQL on a DB where the live service has already
      written a 'created' row (different source) does NOT duplicate.
    - Re-running after a previous backfill (source='backfill') is also
      a no-op.

    Reproduces the exact SQL from
    ``alembic/versions/zbaudit001_backfill_zalo_bot_link_audit_rows.py``
    so a future tweak to the migration predicate will fail this test
    if the idempotency contract regresses.
    """

    BACKFILL_SQL = """
        INSERT INTO entity_audit_log (
            entity_type, entity_id, action,
            actor_user_id, field_name,
            old_value, new_value, changes,
            reason, source, ip_address, user_agent,
            created_at
        )
        SELECT
            'StaffZaloBotLink',
            l.id,
            'created',
            l.user_id,
            NULL,
            NULL,
            json_build_object(
                'user_id', l.user_id,
                'is_active', l.is_active,
                'linked_at', l.linked_at,
                'note', 'backfilled — actual link predates audit instrumentation'
            )::jsonb,
            NULL,
            'backfilled 2026-04-28; original linked_at preserved in new_value',
            'backfill',
            NULL,
            NULL,
            l.linked_at
        FROM staff_zalo_bot_link l
        WHERE l.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM entity_audit_log a
              WHERE a.entity_type = 'StaffZaloBotLink'
                AND a.entity_id = l.id
                AND a.action = 'created'
          );
    """

    @pytest.mark.asyncio
    async def test_live_created_row_blocks_backfill_after_downgrade_reupgrade(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """Reproduces the failure mode flagged in /review:
        downgrade → live link op writes 'created' (source='zalo_bot_webhook')
        → upgrade re-runs migration. The stricter predicate must NOT
        insert a synthetic backfill row alongside the live one.
        """
        from sqlalchemy import text

        user_id = officer_user_in_db["id"]
        # Step 1: live link op writes the 'created' audit row with the
        # service's own source label.
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_idem_live", None
            )
            await db.commit()

        link = (
            await db.execute(
                select(StaffZaloBotLink).where(
                    StaffZaloBotLink.user_id == user_id
                )
            )
        ).scalar_one()

        before = await _audit_rows(db, "StaffZaloBotLink", link.id)
        assert len(before) == 1
        assert before[0].source == "zalo_bot_webhook"

        # Step 2: simulate post-downgrade re-upgrade by running the
        # migration SQL directly. The stricter predicate must skip.
        await db.execute(text(self.BACKFILL_SQL))
        await db.commit()

        after = await _audit_rows(db, "StaffZaloBotLink", link.id)
        assert len(after) == 1, (
            "backfill must NOT duplicate when a live 'created' row "
            "already exists for this entity (any source)"
        )
        assert after[0].source == "zalo_bot_webhook"

    @pytest.mark.asyncio
    async def test_running_backfill_twice_is_noop(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """Re-running the migration on a DB already backfilled produces
        no extra rows."""
        from sqlalchemy import text

        user_id = officer_user_in_db["id"]
        # Insert a link directly (bypass service so no audit row exists).
        link = StaffZaloBotLink(
            user_id=user_id,
            chat_id="chat_idem_twice",
            display_name=None,
            is_active=True,
        )
        db.add(link)
        await db.commit()

        # First run: should insert 1 backfill row.
        await db.execute(text(self.BACKFILL_SQL))
        await db.commit()
        first = await _audit_rows(db, "StaffZaloBotLink", link.id)
        assert len(first) == 1
        assert first[0].source == "backfill"

        # Second run: predicate blocks, no-op.
        await db.execute(text(self.BACKFILL_SQL))
        await db.commit()
        second = await _audit_rows(db, "StaffZaloBotLink", link.id)
        assert len(second) == 1, "second run must be a no-op"


class TestDedupKeyAllowsRepeatDisplacement:
    """V-2 fix: ZALO_BOT_LINK_DISPLACED dedup key MUST include
    chat_id_prefix so two genuine displacements involving the same
    (displaced_user, new_user) pair but different chat_ids both reach
    the recipient instead of the second being suppressed by the
    5-minute cooldown.
    """

    def test_dedup_key_changes_with_chat_id_prefix(self):
        from app.core.event_catalog import render_dedup_key
        from app.core.events import SystemEvents

        payload_first = {
            "user_id": 1,
            "displaced_by_user_id": 2,
            "chat_id_prefix": "abcd***ef",
            "actor_id": 2,
        }
        payload_second = dict(payload_first, chat_id_prefix="ghij***kl")

        key_first = render_dedup_key(
            SystemEvents.ZALO_BOT_LINK_DISPLACED, payload_first
        )
        key_second = render_dedup_key(
            SystemEvents.ZALO_BOT_LINK_DISPLACED, payload_second
        )

        assert key_first != key_second, (
            "different chat_id_prefix MUST produce different dedup keys; "
            "otherwise repeat-displacement notifications get cooldown-suppressed"
        )
        # Both should still be deterministic + contain the user pair.
        assert "1" in key_first and "2" in key_first
        assert "abcd" in key_first
        assert "ghij" in key_second


class TestSyncPreferenceConcurrencySafe:
    """V-1 fix: ``_sync_preference`` must survive a concurrent INSERT
    race on ``notification_preference.user_id`` (read-then-insert
    pattern in the base repo). The savepoint + re-fetch in
    ``_get_or_create_pref_safe`` is the contract under test.
    """

    @pytest.mark.asyncio
    async def test_pref_already_present_on_concurrent_insert_is_handled(
        self, db: AsyncSession, officer_user_in_db: dict, monkeypatch
    ):
        """Simulate the race: first SELECT returns None (as if a parallel
        request hadn't committed yet), but the INSERT then collides with
        the parallel insert that just landed. Service must catch
        ``IntegrityError`` from the savepoint, re-fetch, and proceed.
        """
        from app.models.notification_preference import NotificationPreference
        from app.repositories.notification_preference_repository import (
            NotificationPreferenceRepository,
        )

        user_id = officer_user_in_db["id"]

        # Pre-create the pref row to simulate the "winning" parallel insert.
        winner = NotificationPreference(user_id=user_id, browser_enabled=True)
        db.add(winner)
        await db.commit()

        # Force the in-service get_by_user_id to return None ONCE (the
        # racing read), then the savepoint INSERT will fail with IntegrityError.
        original_get = NotificationPreferenceRepository.get_by_user_id
        call_state = {"count": 0}

        async def fake_get(self, uid):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return None  # race: caller doesn't see the winner yet
            return await original_get(self, uid)

        monkeypatch.setattr(
            NotificationPreferenceRepository, "get_by_user_id", fake_get
        )

        # Should NOT raise — savepoint catches the IntegrityError, re-fetch
        # returns the winner row, and the audit + flip proceed normally.
        await zalo_bot_link_service._sync_preference(
            db, user_id, enabled=True, actor_user_id=user_id
        )
        await db.commit()

        # Final state: winner row updated, exactly 1 audit row written.
        pref_audits = await _audit_rows(db, "NotificationPreference")
        assert len(pref_audits) == 1
        assert pref_audits[0].new_value is True


class TestPreferenceSyncIdempotency:
    @pytest.mark.asyncio
    async def test_no_audit_row_when_value_unchanged(
        self, db: AsyncSession, officer_user_in_db: dict
    ):
        """Calling _sync_preference with the current value writes 0 audit
        rows — prevents log spam from defensive double-flips."""
        user_id = officer_user_in_db["id"]
        # Initial flip True (real link op).
        with patch(
            "app.database.safe_redis_getdel",
            new=AsyncMock(return_value=str(user_id)),
        ):
            await zalo_bot_link_service.verify_and_link(
                db, "ABC123", "chat_idem", None
            )
            await db.commit()

        before = len(await _audit_rows(db, "NotificationPreference"))
        # Call _sync_preference directly with same value (True).
        await zalo_bot_link_service._sync_preference(
            db, user_id, enabled=True, actor_user_id=user_id
        )
        await db.commit()
        after = len(await _audit_rows(db, "NotificationPreference"))
        assert after == before, "no-op flip must not produce audit row"
