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
from app.core.constants import SYSTEM_CONSULTATION_METHOD
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
                        models.Consultation.method == SYSTEM_CONSULTATION_METHOD,
                        models.Consultation.notes.like(f"{intake_svc._WEBSITE_NOTE_MARKER}%"),
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

    async def test_email_goes_to_note_not_lead(
        self, db: AsyncSession, configured_unit: int
    ):
        # Email KHÔNG ghi vào Lead.email (tránh xung đột unique + oracle) — vào note.
        result = await _run_intake(
            db, _payload(phone="0901230004", email="parent@example.com")
        )
        lead = await db.get(models.Lead, result.lead_id)
        assert lead.email is None
        cons = (
            await db.execute(
                select(models.Consultation.notes).where(
                    models.Consultation.lead_id == result.lead_id,
                    models.Consultation.method == SYSTEM_CONSULTATION_METHOD,
                        models.Consultation.notes.like(f"{intake_svc._WEBSITE_NOTE_MARKER}%"),
                )
            )
        ).scalar_one()
        assert "parent@example.com" in cons

    async def test_dedup_skips_second_website_consultation(
        self, db: AsyncSession, configured_unit: int
    ):
        # Submit lại trong cửa sổ dedup → KHÔNG chèn thêm website-consultation
        # (chống amplification note/notif/version-churn).
        first = await _run_intake(db, _payload(phone="0901230005"))
        await _run_intake(db, _payload(phone="0901230005"))
        count = (
            await db.execute(
                select(func.count(models.Consultation.id)).where(
                    models.Consultation.lead_id == first.lead_id,
                    models.Consultation.method == SYSTEM_CONSULTATION_METHOD,
                        models.Consultation.notes.like(f"{intake_svc._WEBSITE_NOTE_MARKER}%"),
                )
            )
        ).scalar()
        assert count == 1

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
        # Email lenient: giữ giá trị (chỉ vào note, service KHÔNG ghi Lead.email);
        # non-str/rỗng → None, KHÔNG bao giờ 422 đánh rớt lead.
        assert (
            schemas.PublicLeadIntake(
                full_name="A", phone="0901234567", email="  x@y.z "
            ).email
            == "x@y.z"
        )
        assert (
            schemas.PublicLeadIntake(full_name="A", phone="0901234567", email="").email
            is None
        )
        assert (
            schemas.PublicLeadIntake(full_name="A", phone="0901234567", email=123).email
            is None
        )

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

    async def test_honeypot_returns_generic_200_no_lead(self, db, client, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_INTAKE_API_KEY", "secret-key")
        resp = await client.post(
            self.URL,
            json={**self.BODY, "hp": "i-am-a-bot"},
            headers={"X-API-Key": "secret-key"},
        )
        assert resp.status_code == 200
        # Response GENERIC (không lộ created/updated/noted/lead_id).
        assert resp.json() == {"status": "received"}
        # Honeypot KHÔNG được tạo lead nào.
        count = (
            await db.execute(
                select(func.count(models.Lead.id)).where(
                    models.Lead.phone == "0907654321"
                )
            )
        ).scalar()
        assert count == 0

    async def test_honeypot_whitespace_is_not_bot(self):
        # hp toàn khoảng trắng (autofill) → trim về None → KHÔNG bị coi là bot.
        p = schemas.PublicLeadIntake(full_name="A", phone="0901234567", hp="   ")
        assert p.hp is None

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
        # Exercise đầy đủ router→service→commit→callback→response qua HTTP.
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
        # Response generic (chống enumeration).
        assert resp.json() == {"status": "received"}
        # XÁC NHẬN lead THẬT đã persist trong DB (không chỉ tin response).
        lead = (
            await db.execute(
                select(models.Lead).where(models.Lead.phone == "0907654399")
            )
        ).scalar_one_or_none()
        assert lead is not None
        assert lead.source == "website"
        assert lead.unit_id == seeded_dependencies["unit_id"]


# =============================================================================
# RATE LIMIT — ca ĐỘNG, chạy thật
# =============================================================================
class TestIntakeRateLimit:
    """Chứng minh hợp đồng rate-limit bằng request THẬT.

    Vì sao phải dựng app riêng: ở ``APP_ENV=test`` kho cố ý nâng
    ``RateLimits.PUBLIC_INTAKE`` lên ``10000/hour`` và bỏ qua việc gắn middleware
    limiter, nên không ca nào chạm được trần. Hệ quả là "có endpoint giới hạn
    500/giờ theo API key" trước nay CHƯA TỪNG được chứng minh — chỉ được đọc.

    ⚠️ ĐỘ PHÂN GIẢI của các ca này, nói cho chính xác: chúng gắn một ``Limiter``
    riêng cap thấp nhưng dùng **đúng ``get_intake_key`` của production**, nên thứ
    được chứng minh là *hành vi bucket / băm khoá / 429* của hàm sẽ chạy thật.
    Chúng KHÔNG trực tiếp chứng minh rằng trên route production thì dependency
    ``verify_intake_api_key`` chạy TRƯỚC limiter — thứ tự ấy là hợp đồng của
    FastAPI (dependency chạy trước thân hàm đã bọc decorator) và được canh riêng
    bởi các ca 401/503 ở ``TestIntakeApi``.
    Nginx có giới hạn 30 req/giây/IP nhưng đó là giới hạn KHÁC: nó theo IP, mà
    WordPress gọi server-to-server nên mọi lead đến từ MỘT IP — không thay được
    hợp đồng theo-key này.
    """

    @staticmethod
    def _dung_app(cap: str):
        from fastapi import FastAPI, Request
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded

        from app.core.rate_limits import get_intake_key

        lim = Limiter(key_func=get_intake_key, storage_uri="memory://")
        app = FastAPI()
        app.state.limiter = lim
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        @app.post("/intake")
        @lim.limit(cap, key_func=get_intake_key)
        async def _nhan(request: Request):  # pragma: no cover - thân không phải thứ đang canh
            return {"ok": True}

        return app

    @staticmethod
    async def _goi(app, ip: str, key):
        """Một POST từ ``ip`` với ``X-API-Key=key`` (None = không gửi header)."""
        from httpx import ASGITransport, AsyncClient

        headers = {} if key is None else {"X-API-Key": key}
        transport = ASGITransport(app=app, client=(ip, 40000))
        async with AsyncClient(transport=transport, base_url="http://intake.test") as c:
            resp = await c.post("/intake", headers=headers)
        return resp.status_code

    async def test_cung_key_khac_ip_dung_chung_mot_bucket(self):
        """Đây là lý do tồn tại của ``get_intake_key``: WordPress có thể đổi IP
        (đổi host, thêm proxy) nhưng vẫn phải nằm trong cùng một hạn mức."""
        app = self._dung_app("2/minute")
        key = "K" * 40
        assert await self._goi(app, "10.0.0.1", key) == 200
        assert await self._goi(app, "10.0.0.2", key) == 200
        # Lượt thứ ba từ IP thứ BA — nếu bucket theo IP thì đây sẽ là 200.
        assert await self._goi(app, "10.0.0.3", key) == 429

    async def test_key_sai_khong_tieu_hao_bucket_cua_key_dung(self):
        """Người lạ gửi key sai không được phép làm cạn hạn mức của website thật.

        (Ở production, key sai còn bị dependency chặn 401 TRƯỚC limiter; ca này
        canh lớp thứ hai — kể cả khi lọt tới limiter thì bucket vẫn tách.)
        """
        app = self._dung_app("2/minute")
        that = "T" * 40
        gia = "G" * 40
        assert await self._goi(app, "10.0.0.1", that) == 200  # dùng 1/2
        for _ in range(5):
            await self._goi(app, "10.0.0.9", gia)  # đốt bucket của key giả
        # Key thật vẫn còn đúng 1 lượt — chứng minh hai bucket tách rời.
        assert await self._goi(app, "10.0.0.1", that) == 200
        assert await self._goi(app, "10.0.0.1", that) == 429

    async def test_vuot_cap_tra_dung_429(self):
        """Trần phải CHẶN thật, không chỉ ghi log."""
        app = self._dung_app("1/minute")
        key = "Z" * 40
        assert await self._goi(app, "10.0.0.1", key) == 200
        assert await self._goi(app, "10.0.0.1", key) == 429

    async def test_thieu_key_thi_lui_ve_bucket_theo_ip(self):
        """Không có header ⇒ rơi về ``get_client_ip``: hai IP khác nhau KHÔNG
        được dùng chung hạn mức (nếu không, một kẻ gửi rác có thể khoá cửa của
        mọi người).

        Chính ca này đã bắt được lỗi gốc: nhánh fallback viết
        ``get_remote_address`` — hàm chưa từng được import trong
        ``rate_limits.py`` nên nó ném ``NameError``, và kể cả khi import thì vẫn
        là hàm SAI vì hop trái nhất của ``X-Forwarded-For`` giả mạo được."""
        app = self._dung_app("1/minute")
        assert await self._goi(app, "10.0.0.1", None) == 200
        assert await self._goi(app, "10.0.0.1", None) == 429
        assert await self._goi(app, "10.0.0.2", None) == 200

    async def test_khoa_bucket_khong_chua_secret_tho(self):
        """Key Redis nằm trong keyspace dùng chung — nhét API key thô vào đó là
        tự rò secret ra chỗ ai đọc được Redis cũng thấy."""
        import hashlib
        from types import SimpleNamespace

        from app.core.rate_limits import get_intake_key

        secret = "sieu-bi-mat-khong-duoc-lo-0123456789abcdef"
        req = SimpleNamespace(headers={"X-API-Key": secret})
        khoa = get_intake_key(req)

        assert secret not in khoa, f"API key thô lọt vào key bucket: {khoa!r}"
        assert khoa.startswith("intake_")
        bam = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        assert khoa == f"intake_{bam}"

    async def test_cap_production_van_la_500_moi_gio(self):
        """Trần thật phải giữ nguyên hợp đồng 500/giờ.

        Đọc THẲNG mã nguồn: ``RateLimits.PUBLIC_INTAKE`` được tính lúc import theo
        ``APP_ENV``, nên trong test nó luôn là giá trị nới rộng — kiểm giá trị
        runtime sẽ canh hụt đúng thứ cần canh.
        """
        import re
        from pathlib import Path

        import app.core.rate_limits as rl

        nguon = Path(rl.__file__).read_text(encoding="utf-8")
        dong = [d for d in nguon.splitlines() if d.strip().startswith("PUBLIC_INTAKE")]
        assert len(dong) == 1, f"kỳ vọng đúng một dòng PUBLIC_INTAKE, thấy {dong}"
        assert re.search(r'"500/hour"', dong[0]), (
            f"trần production của intake đã bị đổi khỏi 500/hour: {dong[0].strip()}"
        )


# =============================================================================
# HAI BẤT BIẾN TRUNG TÂM CỦA BẢN TÍCH HỢP
# =============================================================================
class TestIntakeSystemContract:
    """Hai ca này canh đúng hai lỗi đã được tìm ra khi rà bản gốc.

    Không có chúng thì bản vá chỉ là "trông có vẻ đúng".
    """

    async def test_note_website_khong_bi_tinh_la_tu_van_that(
        self, db: AsyncSession, configured_unit: int
    ):
        """Bản ghi do website sinh ra PHẢI vô hình với recency/count.

        Bản gốc dùng ``method="website"`` — một giá trị mà 8+ truy vấn ở
        ``insights_repository`` / ``lead_repository`` / ``officer_repository``
        chưa hiểu, nên chúng đếm nó là một lần officer liên hệ THẬT: reset đồng
        hồ SLA auto-close, méo ``consultation_count``, và có thể chiếm chỗ "cuộc
        tư vấn mới nhất" khiến officer mất quyền sửa/xoá cuộc thật trước đó. Vá
        riêng một repository là không đủ — nên dùng đúng ``method`` hệ thống.
        """
        from app.repositories.lead_repository import LeadRepository

        result = await _run_intake(db, _payload(phone="0901230091"))
        assert result.status == "created"

        # Bản ghi ĐÃ được chèn thật...
        cons = (
            (
                await db.execute(
                    select(models.Consultation).where(
                        models.Consultation.lead_id == result.lead_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(cons) == 1
        assert cons[0].method == SYSTEM_CONSULTATION_METHOD
        assert (cons[0].notes or "").startswith(intake_svc._WEBSITE_NOTE_MARKER)

        # ...nhưng KHÔNG được tính vào aggregate mà cache/SLA đọc.
        agg = await LeadRepository(db).get_consultation_aggregates(result.lead_id)
        assert agg["consultation_count"] == 0, (
            "note website bị đếm là tư vấn thật — nó sẽ méo urgency và reset "
            f"đồng hồ SLA auto-close: {agg}"
        )
        assert agg["last_consultation_at"] is None, (
            f"note website chiếm chỗ 'tư vấn mới nhất': {agg}"
        )

    async def test_thieu_system_user_thi_503_va_khong_ghi_gi(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch
    ):
        """Thiếu user hệ thống ⇒ 503, KHÔNG persist — không được trả 200 rồi mất dữ liệu.

        Bản gốc bắt ``ConflictError`` trong ``_insert_system_consultation``, bỏ
        note rồi vẫn trả thành công. Nhưng email / hệ / ngành khách gửi CHỈ nằm
        trong note, nên endpoint sẽ báo ``received`` trong khi phần lớn dữ liệu
        biến mất — WordPress không có cách nào biết để gửi lại.
        """
        monkeypatch.setattr(
            settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", seeded_dependencies["unit_id"]
        )
        # CỐ Ý không seed user 'system' → resolver canonical sẽ không khớp fingerprint.

        phone = "0901230092"
        truoc = (
            await db.execute(select(func.count(models.Lead.id)))
        ).scalar_one()

        with pytest.raises(ServiceUnavailableError):
            await _run_intake(db, _payload(phone=phone))

        await db.rollback()
        sau = (await db.execute(select(func.count(models.Lead.id)))).scalar_one()
        assert sau == truoc, "đã tạo lead dù không ghi được note → mất dữ liệu ngầm"

        # Và KHÔNG có consultation mồ côi nào.
        assert (
            await db.execute(
                select(func.count(models.Consultation.id)).where(
                    models.Consultation.method == SYSTEM_CONSULTATION_METHOD
                )
            )
        ).scalar_one() == 0


# =============================================================================
# CONCURRENCY THẬT — hai session, hai transaction
# =============================================================================
class TestIntakeConcurrency:
    """Kế hoạch (§9 mục 5) đòi double-submit ĐỒNG THỜI thật.

    Ca `TestIntakeRaceFallback` ở trên chỉ *mock* ``DuplicateResourceError`` —
    nó chứng minh nhánh XỬ LÝ race chạy đúng, KHÔNG chứng minh advisory lock
    thật sự chặn được race. Hai việc khác nhau: cái đầu kiểm code, cái sau kiểm
    hành vi của Postgres dưới hai transaction song song.
    """

    async def test_double_submit_dong_thoi_chi_tao_MOT_lead(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch
    ):
        import asyncio

        from app.database import AsyncSessionLocal

        monkeypatch.setattr(
            settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", seeded_dependencies["unit_id"]
        )
        await _seed_system_user(db)
        # Phải COMMIT: hai session dưới đây là kết nối RIÊNG, không thấy dữ liệu
        # còn nằm trong transaction chưa commit của fixture.
        await db.commit()

        phone = "0901230099"
        goi_khoa: list[str] = []
        that = intake_svc._advisory_lock_phone

        async def _khoa_co_ghi_nhan(session, phone_normalized):
            goi_khoa.append(phone_normalized)
            return await that(session, phone_normalized)

        monkeypatch.setattr(intake_svc, "_advisory_lock_phone", _khoa_co_ghi_nhan)

        # Đếm số lần THẬT SỰ gọi create_lead — đây là phép phân biệt dứt điểm
        # cho TÁC DỤNG của khoá. Có khoá: lượt hai chờ, rồi tìm thấy lead của
        # lượt một ⇒ create_lead chạy ĐÚNG MỘT lần. Không khoá: cả hai cùng tra
        # ra rỗng rồi cùng gọi create_lead ⇒ hai lần, một lượt vỡ UNIQUE và đi
        # nhánh fallback. Đo được: bỏ phép đếm này thì gỡ hẳn advisory lock ca
        # vẫn XANH, vì partial unique index đỡ hộ — tức ca chỉ đo kết quả chứ
        # không đo khoá.
        goi_create: list[int] = []
        create_that = intake_svc.lead_service.create_lead

        async def _create_co_dem(session, lead_in, created_by=None):
            goi_create.append(1)
            return await create_that(session, lead_in, created_by=created_by)

        monkeypatch.setattr(
            intake_svc.lead_service, "create_lead", _create_co_dem
        )

        async def _mot_request():
            """Mô phỏng ĐÚNG vòng đời router: session riêng → gọi → commit."""
            async with AsyncSessionLocal() as s:
                ket, _cb = await intake_svc.intake_public_lead(
                    s, _payload(phone=phone)
                )
                await s.commit()
                return ket

        # ⚠️ Mở hai `patch` ĐÚNG MỘT LẦN, BÊN NGOÀI `gather`.
        #
        # `patch` sửa thuộc tính ở cấp MODULE. Mở nó bên trong mỗi coroutine thì hai
        # context chồng lên nhau trên cùng một object toàn cục: coroutine B vào khi A
        # đã thay, nên B lưu bản 'gốc' CHÍNH LÀ mock của A; thoát sai thứ tự là mock
        # ở lại module sau khi ca kết thúc, và ca chạy sau trong cùng phiên sẽ thấy
        # một `AsyncMock` thay vì hàm thật — hỏng theo kiểu phụ thuộc thứ tự, rất khó
        # truy. Ngoài `gather` thì chỉ có đúng một cặp vào/ra.
        goc_score = intake_svc.lead_service.calculate_lead_score
        import app.celery_utils as _celery_utils

        goc_task = _celery_utils.process_automatic_lead_assignment_task

        with (
            patch(
                "app.services.lead_service.calculate_lead_score",
                new_callable=AsyncMock,
                return_value=30,
            ),
            patch("app.celery_utils.process_automatic_lead_assignment_task"),
        ):
            r1, r2 = await asyncio.gather(_mot_request(), _mot_request())

        # Không rò global state: hai symbol phải trở về ĐÚNG object gốc.
        assert intake_svc.lead_service.calculate_lead_score is goc_score, (
            "patch không khôi phục `calculate_lead_score` — module còn dính mock"
        )
        assert (
            _celery_utils.process_automatic_lead_assignment_task is goc_task
        ), "patch không khôi phục `process_automatic_lead_assignment_task`"
        # Dùng lớp CƠ SỞ ``Mock``: ``patch`` không có ``new_callable`` tạo
        # ``MagicMock`` chứ không phải ``AsyncMock``, nên kiểm riêng ``AsyncMock``
        # sẽ KHÔNG phủ được symbol thứ hai. ``MagicMock`` và ``AsyncMock`` đều là
        # con của ``Mock``.
        from unittest.mock import Mock

        assert not isinstance(
            intake_svc.lead_service.calculate_lead_score, Mock
        ), "còn mock sót lại trong app.services.lead_service"
        assert not isinstance(
            _celery_utils.process_automatic_lead_assignment_task, Mock
        ), "còn mock sót lại trong app.celery_utils"

        # 1) Advisory lock ĐÃ được xin ở cả hai lượt, cùng một khoá.
        assert goi_khoa == [phone, phone], (
            f"advisory lock không chạy đủ hai lượt: {goi_khoa}"
        )
        assert len(goi_create) == 1, (
            "advisory lock KHÔNG serialize được: create_lead chạy "
            f"{len(goi_create)} lần ⇒ hai lượt cùng đi qua nhánh tạo mới và "
            "chỉ còn UNIQUE index đỡ. Khoá đang không có tác dụng."
        )

        # 2) Kết quả quan sát được: đúng MỘT lead, không 500/409.
        so_lead = (
            await db.execute(
                select(func.count(models.Lead.id)).where(models.Lead.phone == phone)
            )
        ).scalar_one()
        assert so_lead == 1, f"double-submit đồng thời tạo {so_lead} lead"

        trang_thai = sorted([r1.status, r2.status])
        assert trang_thai[0] == "created", (
            f"kỳ vọng đúng một lượt 'created', thấy {trang_thai}"
        )
        assert trang_thai[1] in ("updated", "noted"), (
            f"lượt thứ hai phải là updated/noted, thấy {trang_thai}"
        )
        assert r1.lead_id == r2.lead_id, "hai lượt trả về hai lead khác nhau"

        # 3) Và đúng MỘT note website — không nhân đôi timeline.
        so_note = (
            await db.execute(
                select(func.count(models.Consultation.id)).where(
                    models.Consultation.lead_id == r1.lead_id,
                    models.Consultation.method == SYSTEM_CONSULTATION_METHOD,
                )
            )
        ).scalar_one()
        assert so_note == 1, f"tạo {so_note} note cho cùng một lượt đăng ký"


# =============================================================================
# VALIDATOR CỦA CẤU HÌNH — đi qua pydantic thật, không monkeypatch
# =============================================================================
class TestIntakeApiKeyValidator:
    """Mọi ca khác trong tệp này ``monkeypatch.setattr(settings, ...)`` nên chúng
    ĐI VÒNG validator. Khoá này là thứ duy nhất đứng giữa Internet và một đường
    ghi vào pipeline lead, nên phải có ca đi qua đúng đường pydantic."""

    @staticmethod
    def _kiem(gia_tri):
        """Dựng ``Settings`` THẬT qua pydantic — không gọi validator trực tiếp.

        Gọi thẳng hàm validator sẽ bỏ qua lớp ép kiểu và thứ tự chạy của
        pydantic, tức lại kiểm một thứ khác với đường chạy thật. Đây chính là
        cái bẫy mà mọi ca khác trong tệp này đang mắc khi ``monkeypatch`` vào
        instance ``settings`` đã dựng xong.
        """
        from pydantic import ValidationError

        from app.config import Settings

        try:
            cau_hinh = Settings(PUBLIC_INTAKE_API_KEY=gia_tri)
        except ValidationError as e:  # pydantic bọc ValueError của validator
            raise ValueError(str(e)) from e
        return cau_hinh.PUBLIC_INTAKE_API_KEY

    def test_rong_van_hop_le_giu_che_do_503(self):
        """Rỗng = chưa cấu hình ⇒ endpoint trả 503. Đây là trạng thái AN TOÀN,
        không được coi là lỗi cấu hình."""
        assert self._kiem("") == ""
        assert self._kiem("   ") == ""

    def test_khoa_qua_ngan_bi_tu_choi(self):
        """`"x"` lọt qua phép kiểm khác-rỗng nhưng không cho chút entropy nào,
        đồng thời TẮT chế độ 503 an toàn — tệ hơn cả để trống."""
        with pytest.raises(ValueError) as e:
            self._kiem("x" * 8)
        assert "PUBLIC_INTAKE_API_KEY" in str(e.value)

    @pytest.mark.parametrize("xau", ["CHANGE_ME", "YOUR-KEY", "PLACEHOLDER", "TODO"])
    def test_placeholder_bi_tu_choi(self, xau):
        """Giá trị mẫu copy từ tài liệu phải bị chặn, kể cả khi đủ dài."""
        with pytest.raises(ValueError) as e:
            self._kiem(xau + "a" * 40)
        assert xau in str(e.value)

    def test_khoa_du_manh_duoc_nhan(self):
        import secrets

        khoa = secrets.token_urlsafe(32)
        assert self._kiem(khoa) == khoa

    def test_trim_khoang_trang_truoc_khi_do_do_dai(self):
        """Khoá dán từ tệp env thường dính khoảng trắng — phải đo độ dài THẬT."""
        khoa = "k" * 40
        assert self._kiem(f"  {khoa}  ") == khoa
        with pytest.raises(ValueError):
            self._kiem("   " + "k" * 8 + "   ")
