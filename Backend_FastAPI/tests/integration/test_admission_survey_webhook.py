"""Integration tests for ``user_feedback`` webhook (Phase E.5).

Locks five invariants through the real /api/webhooks/zalo endpoint:

1. **Happy path** — known tracking_id creates a feedback row with
   profile_id populated.
2. **Unknown tracking_id** — row still persisted with profile_id=NULL
   (audit path, no silent drop).
3. **Idempotent re-delivery** — second POST with same tracking_id
   updates the existing row rather than inserting a duplicate;
   unique constraint on tracking_id is the lock.
4. **Malformed rate** — 200-acked, nothing persisted, caller doesn't
   see the validation error (no retry storm from Zalo).
5. **Ignored event** — non-``user_feedback`` event_name leaves the
   feedback table untouched.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings
from app.main import app


def _sign_body(body: bytes) -> str:
    """Compute X-ZEvent-Signature the same way the gateway verifies it
    (see zalo_gateway.verify_webhook_signature). Using the same secret
    fallback chain ZALO_WEBHOOK_SECRET or ZALO_APP_SECRET."""
    secret = settings.ZALO_WEBHOOK_SECRET or settings.ZALO_APP_SECRET or ""
    return hmac.new(
        key=secret.encode(), msg=body, digestmod=hashlib.sha256
    ).hexdigest()


async def _post_signed(client: AsyncClient, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        "/api/webhooks/zalo",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-ZEvent-Signature": _sign_body(body),
        },
    )


def _feedback_payload(
    *,
    tracking_id: str,
    rate: int = 5,
    note: str = "Tôi rất hài lòng.",
    tags=None,
    msg_id: str = "zalomsg_abc123",
    event_name: str = "user_feedback",
):
    """Matches the schema at
    developers.zalo.me/docs/zalo-notification-service/webhook/
    su-kien-nguoi-dung-phan-hoi-template-danh-gia-dich-vu."""
    return {
        "event_name": event_name,
        "app_id": "2074138120372622546",
        "oa_id": "2074138120372622547",
        "timestamp": "1602560967477",
        "message": {
            "msg_id": msg_id,
            "rate": rate,
            "note": note,
            "submit_time": "1616673095659",
            "feedbacks": tags if tags is not None else ["Nhân viên vui vẻ"],
            "tracking_id": tracking_id,
        },
    }


async def _approved_profile_with_tracking(
    db, seeded_dependencies, tracking_id: str
):
    lead = models.Lead(
        full_name="Survey Webhook",
        phone="0901234567",
        source="Website",
        unit_id=seeded_dependencies["unit_id"],
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        academic_year=2026,
        status="approved",
        applied_rules={},
        approved_at=datetime.now(timezone.utc) - timedelta(days=45),
        survey_sent_at=datetime.now(timezone.utc),
        survey_tracking_id=tracking_id,
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest.fixture
def zalo_signing_secret(monkeypatch):
    """Dev/test envs don't ship a Zalo secret; set one so
    verify_webhook_signature has a key to HMAC against. Must fire BEFORE
    any test body that calls _sign_body() or _post_signed() so both
    sides use the same value."""
    monkeypatch.setattr(settings, "ZALO_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(settings, "ZALO_WEBHOOK_SECRET", "")
    yield


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.usefixtures("zalo_signing_secret")
class TestUserFeedbackWebhook:
    async def test_happy_path_persists_with_profile(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        tracking = "survey_happy_e5_01"
        profile = await _approved_profile_with_tracking(
            db, seeded_dependencies, tracking
        )
        await db.commit()

        payload = _feedback_payload(tracking_id=tracking, rate=4)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post_signed(client, payload)

        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id == tracking
                )
            )
        ).scalar_one()
        assert row.profile_id == profile.id
        assert row.rate == 4
        assert row.note == "Tôi rất hài lòng."
        assert row.feedback_tags == ["Nhân viên vui vẻ"]

    async def test_unknown_tracking_id_persists_with_null_profile(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        payload = _feedback_payload(
            tracking_id="survey_ghost_id_not_in_db_01", rate=3
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post_signed(client, payload)

        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id
                    == "survey_ghost_id_not_in_db_01"
                )
            )
        ).scalar_one()
        assert row.profile_id is None
        assert row.rate == 3

    async def test_repeat_delivery_updates_same_row(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        tracking = "survey_idempotent_e5_01"
        await _approved_profile_with_tracking(db, seeded_dependencies, tracking)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = _feedback_payload(tracking_id=tracking, rate=2, note="bad")
            await _post_signed(client, first)

            second = _feedback_payload(
                tracking_id=tracking, rate=5, note="changed my mind", tags=["Hướng dẫn tận tình"],
            )
            await _post_signed(client, second)

        rows = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id == tracking
                )
            )
        ).scalars().all()
        assert len(rows) == 1  # upsert, not insert
        assert rows[0].rate == 5
        assert rows[0].note == "changed my mind"
        assert rows[0].feedback_tags == ["Hướng dẫn tận tình"]

    async def test_malformed_rate_200_acks_without_persist(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        payload = _feedback_payload(
            tracking_id="survey_malformed_e5_01", rate=99
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post_signed(client, payload)

        # 200 to stop Zalo retry; row not persisted.
        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id
                    == "survey_malformed_e5_01"
                )
            )
        ).scalar_one_or_none()
        assert row is None

    async def test_unsigned_request_200_acks_without_persist(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        """Public endpoint cannot be used to plant synthetic feedback —
        missing signature must 200-ack but skip persistence."""
        tracking = "survey_unsigned_e5_01"
        await _approved_profile_with_tracking(db, seeded_dependencies, tracking)
        await db.commit()

        payload = _feedback_payload(tracking_id=tracking, rate=5)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Plain POST — no X-ZEvent-Signature header
            resp = await client.post("/api/webhooks/zalo", json=payload)

        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id == tracking
                )
            )
        ).scalar_one_or_none()
        assert row is None

    async def test_wrong_signature_200_acks_without_persist(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        tracking = "survey_wrongsig_e5_01"
        await _approved_profile_with_tracking(db, seeded_dependencies, tracking)
        await db.commit()

        payload = _feedback_payload(tracking_id=tracking, rate=5)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/webhooks/zalo",
                json=payload,
                headers={"X-ZEvent-Signature": "deadbeef" * 8},
            )

        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id == tracking
                )
            )
        ).scalar_one_or_none()
        assert row is None

    async def test_non_user_feedback_event_is_ignored(
        self, db: AsyncSession, seeded_dependencies: dict,
    ):
        payload = _feedback_payload(
            tracking_id="survey_wrong_event_e5_01",
            event_name="user_follow_oa",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post_signed(client, payload)

        assert resp.status_code == 200
        row = (
            await db.execute(
                select(models.AdmissionSurveyFeedback).where(
                    models.AdmissionSurveyFeedback.tracking_id
                    == "survey_wrong_event_e5_01"
                )
            )
        ).scalar_one_or_none()
        assert row is None
