# app/services/sms_landing_service.py
"""
Business logic landing công khai `/lp/{code}` (PR-5): trả nội dung campaign
(read-only, KHÔNG lộ PII recipient) + trạng thái đã-opt-out; và xử lý opt-out
công khai từ landing (idempotent, source='landing_optout').

KHÔNG import fastapi; raise domain exception; service flush (router commit).
Landing GET KHÔNG ghi click (đã ghi ở /r/). Xem §19.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.sms_engagement_repository import SmsEngagementRepository
from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.schemas import sms as sms_schemas
from app.services.sms_resolve import GENERIC_404, ResolvedCode, resolve_code
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_url import host_in_allowlist

log = logging.getLogger(__name__)


class SmsLandingService:
    """Landing read-only + opt-out công khai (campaign HOẶC consult)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsTrackingRepository(db)
        self.engagement_repo = SmsEngagementRepository(db)

    async def _phone_for(self, resolved: ResolvedCode) -> str:
        """phone_normalized của nguồn (recipient snapshot / consult JOIN contact,
        resolve_code đã nạp sẵn). Raise 404 nếu consult contact đã xoá (không
        opt-out/landing được)."""
        phone = resolved.phone_normalized
        if not phone:
            raise ResourceNotFoundError(detail=GENERIC_404)
        return phone

    async def get_landing(self, code: str) -> sms_schemas.SmsLandingResponse:
        resolved = await resolve_code(self.repo, code, enforce_expiry=True)
        phone = await self._phone_for(resolved)
        already = await self.repo.is_phone_opted_out(phone)

        headline = body = cta_label = cta_url = None
        if resolved.kind == "campaign":
            campaign = resolved.campaign
            headline = campaign.landing_headline
            body = campaign.landing_body
            # CTA external → re-check allowlist lúc render; ngoài → ẩn CTA + log.
            cta_label = campaign.landing_cta_label
            cta_url = campaign.landing_cta_url
            if cta_url and not host_in_allowlist(cta_url):
                log.warning(
                    "SMS landing: CTA url ngoài allowlist campaign_id=%s",
                    campaign.id,
                )
                cta_label = cta_url = None
        # consult: MVP không headline/body/CTA campaign — chỉ danh mục ngành.

        # Phase 2 (§16.1): danh mục ngành cho landing 2 tầng (read-only, no
        # session — session chỉ tạo qua POST để tránh crawler tạo phiên rác).
        programs = await self.engagement_repo.list_active_programs()
        return sms_schemas.SmsLandingResponse(
            school_name=settings.SMS_LANDING_SCHOOL_NAME,
            headline=headline,
            body=body,
            cta_label=cta_label,
            cta_url=cta_url,
            consent_notice=settings.SMS_LANDING_CONSENT_NOTICE,
            already_opted_out=already,
            programs=[
                sms_schemas.SmsLandingProgram(
                    id=p.id, name=p.name, code=p.code,
                    degree_level=p.degree_level,
                )
                for p in programs
            ],
        )

    async def public_opt_out(
        self, code: str
    ) -> sms_schemas.SmsPublicOptOutResponse:
        # Opt-out KHÔNG gate hết hạn (NĐ91 — luôn cho từ chối nhận tin).
        resolved = await resolve_code(self.repo, code, enforce_expiry=False)
        phone = await self._phone_for(resolved)
        if await self.repo.get_opt_out(phone) is not None:
            return sms_schemas.SmsPublicOptOutResponse(
                success=True, already_opted_out=True
            )
        try:
            # SAVEPOINT: IntegrityError do race UNIQUE phone chỉ rollback nested,
            # transaction ngoài còn nguyên (router vẫn commit được) — idempotent.
            async with self.db.begin_nested():
                await self.repo.create_opt_out(
                    {
                        "phone_normalized": phone,
                        "source": "landing_optout",
                        "campaign_id": (
                            resolved.campaign.id if resolved.campaign else None
                        ),
                        "contact_id": resolved.contact_id,
                        "observed_at": datetime.now(timezone.utc),
                    }
                )
        except IntegrityError:
            return sms_schemas.SmsPublicOptOutResponse(
                success=True, already_opted_out=True
            )
        # Opt-out MỚI → vô hiệu export batch chưa bàn giao chứa số này (§8.4).
        await self.repo.invalidate_unhanded_exports_for_phone(phone)
        return sms_schemas.SmsPublicOptOutResponse(
            success=True, already_opted_out=False
        )
