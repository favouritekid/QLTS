"""ADM-028 (2026-04-29): magic-link reminder beat task tests.

Pin the idempotency + filter contract so a flapping beat tick or
worker retry can't double-send reminders, and so locked / expired /
confirmed tokens are not pinged.

The beat task runs the inner ``_run`` coroutine via ``run_async_task``
which spawns its own asyncio loop. Tests invoke the registered Celery
task synchronously (``.apply().get()``) to exercise the full code path
without needing a running worker.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.tasks.admission_tasks import (
    check_admission_confirmation_reminders_task,
)

from tests.integration.test_admission_state_transitions import (
    create_test_lead,
    create_admission_profile,
)


pytestmark = pytest.mark.asyncio


async def _seed_lead_contact_rules() -> None:
    """ADM-028 review (P2 2026-04-29): the reminder beat task is now
    pre-flight gated on a NotificationRule with at least one
    ``lead_contact`` external action being enabled. Most reminder tests
    want to exercise the per-token filter logic AFTER that gate, so
    they need both rules wired. Tests that explicitly want the
    pre-flight skip path can call ``_clear_reminder_rules()`` first.
    """
    from sqlalchemy import delete as sa_delete
    from app.services.notification_rule_loader import invalidate_rule_cache

    events = [
        "admission_confirmation_reminder_24h",
        "admission_confirmation_reminder_6h",
    ]
    async with AsyncSessionLocal() as session:
        for event in events:
            await invalidate_rule_cache(event)
            await session.execute(
                sa_delete(models.NotificationRule).where(
                    models.NotificationRule.event == event
                )
            )
        await session.flush()
        for event in events:
            template = models.NotificationTemplate(
                template_code=f"TPL_{event.upper()}",
                name=f"Test {event}",
                title_template="Reminder",
                message_template="Body",
                template_type="system",
            )
            session.add(template)
            await session.flush()
            rule = models.NotificationRule(
                event=event,
                template_id=template.id,
                title_template=template.title_template,
                message_template=template.message_template,
                recipient_config={
                    "resolver_type": "specific_users",
                    "params": {},
                },
                enabled=True,
            )
            session.add(rule)
            await session.flush()
            session.add(
                models.NotificationAction(
                    rule_id=rule.id,
                    step=1,
                    channel="email",
                    delay_minutes=0,
                    config={"external_resolver": "lead_contact"},
                )
            )
        await session.commit()


@pytest.fixture
async def lead_contact_rules_seeded():
    """Auto-applied to every test in this module so the pre-flight
    ``cfg_24h``/``cfg_6h`` gate inside the beat task evaluates to True
    by default. Tests that want the unconfigured-skip path opt out by
    not requesting this fixture and dropping the rules instead."""
    await _seed_lead_contact_rules()


async def _seed_token_with_expiry(
    *,
    unit_id: int,
    admin_user_id: int,
    expires_in: timedelta,
    confirmed: bool = False,
    locked: bool = False,
    reminder_24h_sent: bool = False,
    reminder_6h_sent: bool = False,
    lead_email: str | None = "applicant@test.com",
) -> int:
    """Create lead + approved profile + token at a specific expiry.

    Returns ``token.id`` for downstream introspection.
    """
    lead_id = await create_test_lead(unit_id)
    if lead_email is not None:
        # Override the helper's default email with whatever the test
        # asked for (or set to null for the no-contact path).
        async with AsyncSessionLocal() as s:
            async with s.begin():
                lead = (
                    await s.execute(
                        select(models.Lead).where(models.Lead.id == lead_id)
                    )
                ).scalar_one()
                lead.email = lead_email
    profile = await create_admission_profile(
        lead_id,
        status="approved",
        citizen_id=f"00120{secrets.randbelow(10**7):07d}",
        approved_by_id=admin_user_id,
    )
    expires_at = datetime.now(timezone.utc) + expires_in
    async with AsyncSessionLocal() as session:
        async with session.begin():
            tok = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                token=secrets.token_urlsafe(32),
                expires_at=expires_at,
            )
            if confirmed:
                tok.confirmed_at = datetime.now(timezone.utc)
            if locked:
                tok.locked_at = datetime.now(timezone.utc)
                tok.lock_count = 1
            if reminder_24h_sent:
                tok.reminder_24h_sent_at = datetime.now(timezone.utc)
            if reminder_6h_sent:
                tok.reminder_6h_sent_at = datetime.now(timezone.utc)
            session.add(tok)
            await session.flush()
            return tok.id


async def _reload_token(token_id: int) -> models.AdmissionConfirmationToken:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(models.AdmissionConfirmationToken).where(
                    models.AdmissionConfirmationToken.id == token_id
                )
            )
        ).scalar_one()


def _run_task() -> dict:
    """Invoke the Celery task synchronously and return its result dict."""
    return check_admission_confirmation_reminders_task.apply().get()


# ============================================================================
# 24h window
# ============================================================================


class TestReminder24h:
    async def test_token_in_24h_window_emits_once_and_marks_sent_at(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        """Expiry ~20h away → 24h reminder fires + ``reminder_24h_sent_at``
        is stamped. Re-running the task does not double-send."""
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
        )

        result = _run_task()
        assert result["sent_24h"] >= 1, result
        assert result["sent_6h"] == 0, result

        tok = await _reload_token(token_id)
        assert tok.reminder_24h_sent_at is not None
        assert tok.reminder_6h_sent_at is None

        # Idempotency: second invocation must not re-send.
        first_sent_at = tok.reminder_24h_sent_at
        result_2 = _run_task()
        assert result_2["sent_24h"] == 0, (
            f"second run re-sent 24h reminder: {result_2}"
        )

        tok = await _reload_token(token_id)
        assert tok.reminder_24h_sent_at == first_sent_at, (
            "reminder_24h_sent_at must not be touched on re-run"
        )


# ============================================================================
# 6h window
# ============================================================================


class TestReminder6h:
    async def test_token_in_6h_window_emits_6h_only(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        """Expiry ~3h away → only the 6h reminder fires; 24h is
        suppressed because the window has already collapsed past it.

        The task design also marks ``reminder_24h_sent_at`` on the same
        run so a token issued <6h before expiry doesn't trigger a noisy
        retroactive 24h reminder later."""
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=3),
        )

        result = _run_task()
        assert result["sent_6h"] >= 1, result
        assert result["sent_24h"] == 0, result

        tok = await _reload_token(token_id)
        assert tok.reminder_6h_sent_at is not None
        # The task SHOULD also mark the 24h slot consumed in this case.
        assert tok.reminder_24h_sent_at is not None

    async def test_re_run_does_not_re_send_6h(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=3),
        )

        _run_task()
        tok_first = await _reload_token(token_id)

        result_2 = _run_task()
        assert result_2["sent_6h"] == 0
        assert result_2["sent_24h"] == 0

        tok_second = await _reload_token(token_id)
        assert tok_second.reminder_6h_sent_at == tok_first.reminder_6h_sent_at


# ============================================================================
# Filter: ineligible tokens skipped
# ============================================================================


class TestSkipsIneligible:
    """Locked / confirmed / expired / already-reminded tokens must
    not be re-pinged."""

    async def test_locked_token_skipped(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
            locked=True,
        )

        result = _run_task()
        assert result["sent_24h"] == 0, result

        tok = await _reload_token(token_id)
        assert tok.reminder_24h_sent_at is None

    async def test_confirmed_token_skipped(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
            confirmed=True,
        )

        result = _run_task()
        assert result["sent_24h"] == 0
        tok = await _reload_token(token_id)
        assert tok.reminder_24h_sent_at is None

    async def test_expired_token_skipped(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=-1),  # already expired
        )

        result = _run_task()
        assert result["sent_24h"] == 0
        assert result["sent_6h"] == 0
        tok = await _reload_token(token_id)
        assert tok.reminder_24h_sent_at is None
        assert tok.reminder_6h_sent_at is None

    async def test_already_reminded_token_skipped(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
            reminder_24h_sent=True,
        )

        result = _run_task()
        assert result["sent_24h"] == 0


# ============================================================================
# No contact channel
# ============================================================================


class TestSkipsNoContact:
    """Lead without email/phone → mark both windows consumed so the
    token drops out of future scans (per task docstring)."""

    async def test_external_delivery_via_lead_contact_creates_delivery_row(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        """When a NotificationRule is wired with an action whose
        ``config.external_resolver = "lead_contact"``, running the
        reminder task must produce a ``NotificationDelivery`` row for
        the applicant — proves the catalog ↔ rule ↔ task chain
        actually delivers, not just stamps ``reminder_24h_sent_at``.

        This pins the operational contract: ops can wire delivery
        through the admin UI, the beat task fires, the dispatcher
        picks up the rule, and ``notification_delivery`` rows accumulate.
        """
        from sqlalchemy import delete as sa_delete
        from app.services.notification_rule_loader import invalidate_rule_cache

        # Seed a rule + action with lead_contact external resolver for
        # the 24h reminder event. Same shape as
        # ``test_per_action_dispatch.py::_seed_rule_with_actions``.
        async with AsyncSessionLocal() as session:
            await invalidate_rule_cache(
                "admission_confirmation_reminder_24h"
            )
            await session.execute(
                sa_delete(models.NotificationRule).where(
                    models.NotificationRule.event
                    == "admission_confirmation_reminder_24h"
                )
            )
            await session.flush()

            template = models.NotificationTemplate(
                template_code="TPL_TEST_CONFIRM_REMINDER_24H",
                name="Test reminder 24h",
                title_template="Còn ${hours_remaining}h",
                message_template=(
                    "${lead_name}, link xác nhận hết hạn ${expires_at_iso}"
                ),
                template_type="system",
            )
            session.add(template)
            await session.flush()

            rule = models.NotificationRule(
                event="admission_confirmation_reminder_24h",
                template_id=template.id,
                title_template=template.title_template,
                message_template=template.message_template,
                # Internal recipients = none; external delivery via
                # the action below.
                recipient_config={"resolver_type": "specific_users", "params": {}},
                enabled=True,
            )
            session.add(rule)
            await session.flush()
            session.add(
                models.NotificationAction(
                    rule_id=rule.id,
                    step=1,
                    channel="email",
                    delay_minutes=0,
                    config={"external_resolver": "lead_contact"},
                )
            )
            await session.commit()

        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
        )

        result = _run_task()
        assert result["sent_24h"] >= 1, result

        # Delivery row must exist for the applicant via lead_contact.
        async with AsyncSessionLocal() as session:
            from app.models.notification_delivery import NotificationDelivery

            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.id == token_id
                    )
                )
            ).scalar_one()
            profile = (
                await session.execute(
                    select(models.AdmissionProfile).where(
                        models.AdmissionProfile.id == tok.profile_id
                    )
                )
            ).scalar_one()
            lead = (
                await session.execute(
                    select(models.Lead).where(
                        models.Lead.id == profile.lead_id
                    )
                )
            ).scalar_one()

            deliveries = (
                await session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.event
                        == "admission_confirmation_reminder_24h"
                    )
                )
            ).scalars().all()
            # At least one delivery row created.
            assert len(deliveries) >= 1, (
                f"expected ≥1 NotificationDelivery row for reminder, "
                f"got {len(deliveries)}. lead.email={lead.email!r}"
            )
            # The delivery must target the applicant's email (not an
            # internal user_id) — that's the lead_contact contract.
            # NotificationDelivery.destination holds the normalized
            # email/phone for external delivery.
            applicant_delivery = next(
                (d for d in deliveries if d.destination == lead.email),
                None,
            )
            assert applicant_delivery is not None, (
                f"expected delivery to destination={lead.email}, got "
                f"destinations={[d.destination for d in deliveries]}"
            )
            assert applicant_delivery.channel == "email"

    async def test_unconfigured_rule_skips_without_stamping_marker(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """P2 review (2026-04-29): when no NotificationRule has an
        action with ``external_resolver='lead_contact'``, the task
        must NOT stamp ``reminder_*_sent_at`` — otherwise the token
        burns its only retry window in the unconfigured deploy shape
        and never re-fires once ops finally wires the rule.

        Note: NO ``lead_contact_rules_seeded`` fixture — this test
        deliberately exercises the unconfigured path.
        """
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
        )

        result = _run_task()
        assert result["sent_24h"] == 0, result
        assert result["sent_6h"] == 0, result

        tok = await _reload_token(token_id)
        # Critical: marker NOT stamped, so a future scan after ops
        # configures the rule will retry this token.
        assert tok.reminder_24h_sent_at is None, (
            "reminder_24h_sent_at must remain NULL when no rule "
            "is configured — otherwise the retry window is lost"
        )
        assert tok.reminder_6h_sent_at is None

    async def test_no_contact_marks_both_windows_consumed(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        lead_contact_rules_seeded,
    ):
        token_id = await _seed_token_with_expiry(
            unit_id=seed_lead_dependencies["unit_id"],
            admin_user_id=admin_user_in_db["id"],
            expires_in=timedelta(hours=20),
            lead_email=None,
        )
        # Strip phone too — the helper sets a default phone.
        async with AsyncSessionLocal() as s:
            async with s.begin():
                tok = (
                    await s.execute(
                        select(models.AdmissionConfirmationToken).where(
                            models.AdmissionConfirmationToken.id == token_id
                        )
                    )
                ).scalar_one()
                lead = (
                    await s.execute(
                        select(models.Lead).where(
                            models.Lead.id == tok.profile_id  # NB: profile.lead_id
                        )
                    )
                ).scalar_one_or_none()
                # The above lookup uses profile_id as a stand-in; fix
                # by going via profile -> lead.
                profile = (
                    await s.execute(
                        select(models.AdmissionProfile).where(
                            models.AdmissionProfile.id == tok.profile_id
                        )
                    )
                ).scalar_one()
                lead = (
                    await s.execute(
                        select(models.Lead).where(
                            models.Lead.id == profile.lead_id
                        )
                    )
                ).scalar_one()
                lead.phone = ""
                lead.email = None

        result = _run_task()
        assert result["sent_24h"] == 0
        assert result["sent_6h"] == 0
        # Skipped row counter advanced.
        assert result["skipped_no_email_phone"] >= 1

        tok = await _reload_token(token_id)
        # Both windows marked consumed so re-scans drop this token.
        assert tok.reminder_24h_sent_at is not None
        assert tok.reminder_6h_sent_at is not None
