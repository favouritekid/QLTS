# tests/services/test_public_lead_intake.py
"""Tests cho website lead intake (public endpoint + service).

Service-level: created / updated / noted (terminal) / race-fallback / config 503.
Unit-level: chuẩn hoá education, helper has-profile, schema validate phone/email.
API-level: X-API-Key 503/401, honeypot 200 giả.

Xem Documents/WEBSITE_LEAD_INTAKE_PLAN.md.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings
from app.security import get_password_hash
from app.services import public_lead_intake_service as intake_svc
from app.utils.exceptions import ServiceUnavailableError

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# =============================================================================
# HELPERS / FIXTURES
# =============================================================================
async def _seed_system_user(db: AsyncSession) -> models.User:
    """Tài khoản kỹ thuật 'system' khớp fingerprint của resolver canonical."""
    user = models.User(
        username="system",
        email="system@qlts.internal",
        password_hash=get_password_hash("SystemX123!"),
        full_name="System Policy",
        role="user",
        status="inactive",
        unit_id=None,
    )
    db.add(user)
    await db.flush()
    return user


def _payload(**kw) -> schemas.PublicLeadIntake:
    base = dict(
        full_name="Nguyễn Văn A",
        phone="0901234567",
        he="Cao đẳng",
        nganh_xet="Công nghệ thông tin",
        nganh_dang_ky="CNTT",
        address="123 Đường ABC, TP Buôn Ma Thuột",
        education_level_raw="Cao đẳng",
    )
    base.update(kw)
    return schemas.PublicLeadIntake(**base)


async def _run_intake(db: AsyncSession, payload: schemas.PublicLeadIntake):
    """Chạy service như router: gọi → commit → await callback. Mock celery + score."""
    with (
        patch(
            "app.services.lead_service.calculate_lead_score",
            new_callable=AsyncMock,
            return_value=30,
        ),
        patch("app.celery_utils.process_automatic_lead_assignment_task"),
    ):
        result, cb = await intake_svc.intake_public_lead(db, payload)
        await db.commit()
        if cb:
            await cb()
    return result


@pytest_asyncio.fixture
async def configured_unit(
    db: AsyncSession, seeded_dependencies: dict, monkeypatch
) -> int:
    """Cấu hình đơn vị mặc định cho intake + seed system user."""
    monkeypatch.setattr(
        settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", seeded_dependencies["unit_id"]
    )
    await _seed_system_user(db)
    return seeded_dependencies["unit_id"]


# =============================================================================
# SERVICE — CREATED
# =============================================================================
class TestIntakeCreated:
    async def test_new_phone_creates_website_lead(
        self, db: AsyncSession, configured_unit: int
    ):
        result = await _run_intake(db, _payload(phone="0901230001"))

        assert result.status == "created"
        lead = await db.get(models.Lead, result.lead_id)
        assert lead.source == "website"
        assert lead.unit_id == configured_unit
        assert lead.location == "123 Đường ABC, TP Buôn Ma Thuột"
        assert lead.education_level == "diploma"  # "Cao đẳng" → diploma
        assert lead.offering_id is None  # D3: KHÔNG auto-map ngành

    async def test_creates_system_consultation_with_note(
        self, db: AsyncSession, configured_unit: int
    ):
        result = await _run_intake(db, _payload(phone="0901230002"))

        rows = (
            (
                await db.execute(
                    select(models.Consultation).where(
                        models.Consultation.lead_id == result.lead_id,
                        models.Consultation.method == "website",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        note = rows[0].notes or ""
        assert "Đăng ký qua website" in note
        assert "Công nghệ thông tin" in note  # ngành nằm trong note

    async def test_pipeline_not_changed_by_intake(
        self, db: AsyncSession, configured_unit: int
    ):
        first = await _run_intake(db, _payload(phone="0901230003"))
        lead = await db.get(models.Lead, first.lead_id)
        before_status = lead.consultation_status_id
        before_stage = lead.pipeline_stage_id
        # Submit lại cùng SĐT (nhánh updated) — system consultation KHÔNG đẩy pipeline.
        await _run_intake(db, _payload(phone="0901230003"))
        await db.refresh(lead)
        assert lead.consultation_status_id == before_status
        assert lead.pipeline_stage_id == before_stage


# =============================================================================
# SERVICE — UPDATED (upsert by phone)
# =============================================================================
class TestIntakeUpdated:
    async def test_duplicate_phone_updates_not_creates(
        self, db: AsyncSession, configured_unit: int
    ):
        await _run_intake(db, _payload(phone="0901230010"))
        result2 = await _run_intake(db, _payload(phone="0901230010", he="Trung cấp"))

        assert result2.status == "updated"
        count = (
            await db.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.phone == "0901230010"
                )
            )
        ).scalar()
        assert count == 1  # KHÔNG tạo trùng

    async def test_canonical_lookup_matches_unformatted_phone(
        self, db: AsyncSession, configured_unit: int
    ):
        # Tạo bằng dạng +84, lần 2 dạng 0... → cùng phone_normalized → updated.
        await _run_intake(db, _payload(phone="+84901230011"))
        result2 = await _run_intake(db, _payload(phone="0901230011"))

        assert result2.status == "updated"
        count = (
            await db.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.phone == "0901230011"
                )
            )
        ).scalar()
        assert count == 1


# =============================================================================
# SERVICE — NOTED (terminal lead, no reopen)
# =============================================================================
class TestIntakeNoted:
    async def test_terminal_lead_noted_not_reopened(
        self, db: AsyncSession, seeded_dependencies: dict, configured_unit: int
    ):
        first = await _run_intake(db, _payload(phone="0901230020"))
        lead = await db.get(models.Lead, first.lead_id)

        # Gán trạng thái terminal phase tư vấn (is_final + phase="consultation").
        term = models.ConsultationStatus(
            id="sts_term_intake",
            name="Da ngung tu van (test)",
            color_code="#000000",
            stage_id=seeded_dependencies["stage_id"],
            is_final=True,
            phase="consultation",
        )
        db.add(term)
        await db.flush()
        lead.consultation_status_id = term.id
        await db.flush()
        await db.commit()

        result = await _run_intake(db, _payload(phone="0901230020"))

        assert result.status == "noted"
        await db.refresh(lead)
        assert lead.consultation_status_id == term.id  # KHÔNG reopen/đổi status


# =============================================================================
# SERVICE — RACE FALLBACK (create_lead raises Duplicate → reload canonical)
# =============================================================================
class TestIntakeRaceFallback:
    async def test_duplicate_on_create_falls_back_to_existing(
        self, db: AsyncSession, configured_unit: int
    ):
        await _run_intake(db, _payload(phone="0901230030"))
        # Lấy existing qua chính method canonical (eager-load consultation_status /
        # admission_profiles) — giống đường reload thật trong service.
        existing = await intake_svc.LeadRepository(
            db
        ).get_active_lead_by_phone_identity("0901230030")
        assert existing is not None

        calls = {"n": 0}

        async def fake_lookup(self, phone_normalized):
            calls["n"] += 1
            return None if calls["n"] == 1 else existing

        from app.utils.exceptions import DuplicateResourceError

        with (
            patch.object(
                intake_svc.LeadRepository,
                "get_active_lead_by_phone_identity",
                fake_lookup,
            ),
            patch.object(
                intake_svc.lead_service,
                "create_lead",
                new_callable=AsyncMock,
                side_effect=DuplicateResourceError("dup"),
            ),
        ):
            result, cb = await intake_svc.intake_public_lead(
                db, _payload(phone="0901230030")
            )
            await db.commit()
            if cb:
                await cb()

        assert result.lead_id == existing.id
        assert result.status in ("updated", "noted")  # KHÔNG để 409 thoát ra


# =============================================================================
# SERVICE — CONFIG (fail-closed 503)
# =============================================================================
class TestIntakeConfig:
    async def test_missing_default_unit_raises_503(self, db: AsyncSession, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", None)
        with pytest.raises(ServiceUnavailableError):
            await intake_svc.intake_public_lead(db, _payload())

    async def test_nonexistent_default_unit_raises_503(
        self, db: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", 99999999)
        with pytest.raises(ServiceUnavailableError):
            await intake_svc.intake_public_lead(db, _payload())


# =============================================================================
# UNIT — helpers & schema
# =============================================================================
class TestIntakeUnit:
    def test_normalize_education(self):
        assert intake_svc._normalize_education("THPT") == "high_school"
        assert intake_svc._normalize_education("Cao đẳng") == "diploma"
        assert intake_svc._normalize_education("Đại học") == "bachelor"
        assert intake_svc._normalize_education("Khác") == "other"
        assert intake_svc._normalize_education("xyz không khớp") is None
        assert intake_svc._normalize_education(None) is None

    def test_lead_has_profile(self):
        # AdmissionProfile hard-delete (không có deleted_at) → chỉ kiểm tra tồn tại.
        assert (
            intake_svc._lead_has_profile(SimpleNamespace(admission_profiles=[]))
            is False
        )
        assert (
            intake_svc._lead_has_profile(SimpleNamespace(admission_profiles=None))
            is False
        )
        assert (
            intake_svc._lead_has_profile(SimpleNamespace(admission_profiles=[object()]))
            is True
        )

    def test_schema_strips_and_truncates(self):
        # Field strip_whitespace là no-op ở pydantic v2 → validator phải strip thật.
        p = schemas.PublicLeadIntake(
            full_name="  Nguyễn A  ", phone="0901234567", address="  "
        )
        assert p.full_name == "Nguyễn A"
        assert p.address is None  # khoảng trắng → None
        # Tên toàn khoảng trắng → 422 (sau strip rỗng, vi phạm required).
        with pytest.raises(ValidationError):
            schemas.PublicLeadIntake(full_name="   ", phone="0901234567")
        # Field mô tả quá dài → TRUNCATE (không 422 đánh rớt lead).
        long_note = "x" * 5000
        p2 = schemas.PublicLeadIntake(
            full_name="A", phone="0901234567", extra_note=long_note
        )
        assert len(p2.extra_note) == 2000
        # Email rác (không có '@') → None thay vì 422.
        p3 = schemas.PublicLeadIntake(
            full_name="A", phone="0901234567", email="not-an-email"
        )
        assert p3.email is None

    def test_schema_rejects_invalid_phone(self):
        with pytest.raises(ValidationError):
            schemas.PublicLeadIntake(full_name="A", phone="123")

    def test_schema_email_optional(self):
        p = schemas.PublicLeadIntake(full_name="A", phone="0901234567")
        assert p.email is None
        # email rỗng → None (không 422)
        p2 = schemas.PublicLeadIntake(full_name="A", phone="0901234567", email="")
        assert p2.email is None


# =============================================================================
# API — X-API-Key gate + honeypot
# =============================================================================
class TestIntakeApi:
    URL = "/api/public/leads/intake"
    BODY = {"full_name": "Nguyễn Văn B", "phone": "0907654321"}

    async def test_api_key_not_configured_503(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "")
        resp = await client.post(self.URL, json=self.BODY)
        assert resp.status_code == 503

    async def test_api_key_wrong_401(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        resp = await client.post(
            self.URL, json=self.BODY, headers={"X-API-Key": "wrong"}
        )
        assert resp.status_code == 401

    async def test_api_key_missing_401(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        resp = await client.post(self.URL, json=self.BODY)
        assert resp.status_code == 401

    async def test_honeypot_returns_fake_200_no_lead(self, db, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        resp = await client.post(
            self.URL,
            json={**self.BODY, "hp": "i-am-a-bot"},
            headers={"X-API-Key": "secret-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["lead_id"] == 0
        # Honeypot KHÔNG được tạo lead nào.
        count = (
            await db.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.phone == "0907654321"
                )
            )
        ).scalar()
        assert count == 0

    async def test_non_ascii_api_key_raises_401_not_typeerror(self, monkeypatch):
        # Test thẳng dependency (httpx tự encode header client-side, khó gửi raw
        # non-ASCII). hmac.compare_digest trên str non-ASCII raise TypeError →
        # fix so sánh BYTES → phải raise AuthenticationError (401), KHÔNG TypeError.
        from app.core.deps import verify_intake_api_key
        from app.utils.exceptions import AuthenticationError

        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        with pytest.raises(AuthenticationError):
            await verify_intake_api_key(x_api_key="ké-bad-\x80")

    async def test_http_happy_path_creates_lead(
        self, db, seeded_dependencies, client, monkeypatch
    ):
        # Exercise đầy đủ router→service→commit→callback→response_model qua HTTP.
        await _seed_system_user(db)
        await db.commit()  # persist unit + system user để app session thấy
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        monkeypatch.setattr(
            settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", seeded_dependencies["unit_id"]
        )
        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch("app.celery_utils.process_automatic_lead_assignment_task"),
        ):
            resp = await client.post(
                self.URL,
                json={"full_name": "Web HTTP Lead", "phone": "0907654399"},
                headers={"X-API-Key": "secret-key"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "created"
        assert body["lead_id"] > 0
