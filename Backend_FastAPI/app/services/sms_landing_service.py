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
from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.schemas import sms as sms_schemas
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_token import compute_token_hash, is_valid_code
from app.utils.sms_url import host_in_allowlist

log = logging.getLogger(__name__)

_GENERIC_404 = "Liên kết không hợp lệ hoặc đã hết hạn"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class SmsLandingService:
    """Landing read-only + opt-out công khai."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsTrackingRepository(db)

    async def _resolve(self, code: str, *, enforce_expiry: bool = True):
        if not is_valid_code(code):
            raise ResourceNotFoundError(detail=_GENERIC_404)
        found = await self.repo.lookup_by_token_hash(compute_token_hash(code))
        if found is None:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        recipient, campaign = found
        # Opt-out KHÔNG gate hết hạn (enforce_expiry=False): nghĩa vụ cho phép
        # từ chối nhận tin phải LUÔN thực hiện được kể cả khi link đã hết hạn
        # (NĐ91). Landing GET vẫn gate (hiện trang hết-hạn thân thiện).
        if enforce_expiry and campaign.link_expires_at and _aware(
            campaign.link_expires_at
        ) <= datetime.now(timezone.utc):
            raise ResourceNotFoundError(detail=_GENERIC_404)
        return recipient, campaign

    async def get_landing(self, code: str) -> sms_schemas.SmsLandingResponse:
        recipient, campaign = await self._resolve(code)
        already = await self.repo.is_phone_opted_out(
            recipient.phone_normalized_snapshot
        )
        # CTA external → re-check allowlist lúc render; ngoài → ẩn CTA + log.
        cta_label = campaign.landing_cta_label
        cta_url = campaign.landing_cta_url
        if cta_url and not host_in_allowlist(cta_url):
            log.warning(
                "SMS landing: CTA url ngoài allowlist campaign_id=%s", campaign.id
            )
            cta_label = cta_url = None
        return sms_schemas.SmsLandingResponse(
            school_name=settings.SMS_LANDING_SCHOOL_NAME,
            headline=campaign.landing_headline,
            body=campaign.landing_body,
            cta_label=cta_label,
            cta_url=cta_url,
            consent_notice=settings.SMS_LANDING_CONSENT_NOTICE,
            already_opted_out=already,
        )

    async def public_opt_out(
        self, code: str
    ) -> sms_schemas.SmsPublicOptOutResponse:
        recipient, campaign = await self._resolve(code, enforce_expiry=False)
        phone = recipient.phone_normalized_snapshot
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
                        "campaign_id": campaign.id,
                        "contact_id": recipient.contact_id,
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
