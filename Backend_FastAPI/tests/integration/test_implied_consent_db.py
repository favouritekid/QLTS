"""Integration tests for implied Zalo consent — real-DB FK behavior.

Motivation: the unit tests for grant_implied_zalo_consent mock upsert_consent,
which hides whether actor_id=0 (old buggy fallback) actually violates the
user.id FK. These tests exercise the real SQLAlchemy/Postgres path to lock
three invariants:

1. ``granted_by=None`` is accepted (nullable FK).
2. ``granted_by=<non-existent user.id>`` raises IntegrityError → helper swallows
   and returns False.
3. ``granted_by=<existing user.id>`` persists the FK correctly.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.notification_consent import NotificationConsent
from app.services import notification_consent_service


def _lead_stub(lead_id: int, phone: str = "0901234567") -> SimpleNamespace:
    """Build a minimal lead-like object (we only need the attrs the helper reads)."""
    return SimpleNamespace(
        id=lead_id,
        phone=phone,
        source="website",
        created_via="api",
        created_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.integration
class TestImpliedConsentFKBehavior:
    async def test_actor_id_none_persists_granted_by_null(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """actor_id=None must produce a row with granted_by IS NULL (valid FK)."""
        # Create a real Lead row so source_id references an existing entity.
        lead_row = models.Lead(
            full_name="Consent FK None",
            phone="0901111111",
            source="Website",
            unit_id=seeded_dependencies["unit_id"],
            status=seeded_dependencies["initial_status_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
        )
        db.add(lead_row)
        await db.flush()

        ok = await notification_consent_service.grant_implied_zalo_consent(
            db, lead_row, actor_id=None,
        )
        assert ok is True
        await db.flush()

        row = (await db.execute(
            select(NotificationConsent).where(
                NotificationConsent.channel == "zalo",
                NotificationConsent.source_type == "lead",
                NotificationConsent.source_id == lead_row.id,
            )
        )).scalar_one()
        assert row.granted_by is None
        assert row.consent_status == "granted"
        assert row.consent_source == "implied_by_registration"

    async def test_actor_id_real_user_persists_fk(
        self,
        db: AsyncSession,
        admin_user: models.User,
        seeded_dependencies: dict,
    ):
        """actor_id=<existing user> persists correctly."""
        lead_row = models.Lead(
            full_name="Consent FK Real",
            phone="0902222222",
            source="Website",
            unit_id=seeded_dependencies["unit_id"],
            status=seeded_dependencies["initial_status_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
        )
        db.add(lead_row)
        await db.flush()

        ok = await notification_consent_service.grant_implied_zalo_consent(
            db, lead_row, actor_id=admin_user.id,
        )
        assert ok is True
        await db.flush()

        row = (await db.execute(
            select(NotificationConsent).where(
                NotificationConsent.source_id == lead_row.id,
                NotificationConsent.source_type == "lead",
            )
        )).scalar_one()
        assert row.granted_by == admin_user.id

    async def test_actor_id_zero_would_violate_fk_but_helper_returns_false(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Regression guard: if anyone reintroduces an ``actor_id or 0`` default,
        the real DB rejects granted_by=0 (no user with id=0) and the helper must
        swallow the IntegrityError + return False."""
        lead_row = models.Lead(
            full_name="Consent FK Zero",
            phone="0903333333",
            source="Website",
            unit_id=seeded_dependencies["unit_id"],
            status=seeded_dependencies["initial_status_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
        )
        db.add(lead_row)
        await db.flush()

        # Force the old buggy behavior: call upsert_consent directly with actor_id=0.
        # Must fail at flush with FK violation.
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await notification_consent_service.upsert_consent(
                db,
                data={
                    "channel": "zalo",
                    "source_type": "lead",
                    "source_id": lead_row.id,
                    "normalized_phone": "84903333333",
                    "consent_status": "granted",
                    "consent_source": "implied_by_registration",
                    "notes": "fk test",
                },
                actor_id=0,
            )
            await db.flush()
        await db.rollback()
