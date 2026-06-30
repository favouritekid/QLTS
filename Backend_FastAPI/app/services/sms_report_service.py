# app/services/sms_report_service.py
"""
Business logic report SMS (PR-5): report click theo ngày/tháng/năm (CTR =
distinct non-bot / recipients handed_off), dashboard 1 campaign, và opt-out
admin (ghi tay + danh sách).

KHÔNG import fastapi; raise domain exception; service flush (router commit).
Xem SMS_MARKETING_MODULE_DESIGN.md §9 / §19.3.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.sms_campaign_repository import SmsCampaignRepository
from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.schemas import sms as sms_schemas
from app.utils.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.masking import mask_phone
from app.utils.phone_helpers import (
    is_vietnam_mobile,
    normalize_and_validate_vietnam_phone,
)
from app.utils.sms_render import has_link

_FMT = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def _fmt_period(dt: datetime, granularity: str) -> str:
    return dt.strftime(_FMT.get(granularity, "%Y-%m-%d"))


def _ctr(distinct_human: int, handed_off: int) -> float:
    return round(distinct_human / handed_off * 100, 2) if handed_off else 0.0


class SmsReportService:
    """Report click + dashboard + opt-out admin."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsTrackingRepository(db)
        self.campaign_repo = SmsCampaignRepository(db)

    # ---------------------------------------------------------------
    # Report click theo granularity
    # ---------------------------------------------------------------
    async def click_report(
        self,
        *,
        granularity: str,
        campaign_id: Optional[int] = None,
        carrier: Optional[str] = None,
        group_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> sms_schemas.SmsClickReport:
        filters = dict(
            campaign_id=campaign_id,
            carrier=carrier,
            group_id=group_id,
            date_from=date_from,
            date_to=date_to,
        )
        buckets = await self.repo.click_buckets(
            granularity=granularity, **filters
        )
        total, human, distinct = await self.repo.click_totals(**filters)
        handed = await self.repo.count_handed_off(
            campaign_id=campaign_id, carrier=carrier, group_id=group_id
        )
        return sms_schemas.SmsClickReport(
            granularity=granularity,
            buckets=[
                sms_schemas.SmsClickBucket(
                    period=_fmt_period(p, granularity),
                    total_clicks=t,
                    human_clicks=h,
                    distinct_contacts_clicked=d,
                )
                for p, t, h, d in buckets
            ],
            total_clicks=total,
            human_clicks=human,
            distinct_contacts_clicked=distinct,
            recipients_handed_off=handed,
            ctr_percent=_ctr(distinct, handed),
        )

    # ---------------------------------------------------------------
    # Dashboard 1 campaign
    # ---------------------------------------------------------------
    async def dashboard(
        self, campaign_id: int
    ) -> sms_schemas.SmsCampaignDashboard:
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        handed = await self.repo.count_handed_off(campaign_id=campaign_id)
        total, human, distinct = await self.repo.click_totals(
            campaign_id=campaign_id
        )
        carrier_dist = await self.repo.carrier_distribution_handed_off(
            campaign_id
        )
        clickers = await self.repo.top_clickers(campaign_id)
        return sms_schemas.SmsCampaignDashboard(
            campaign_id=campaign_id,
            build_revision=campaign.build_revision,
            has_link=has_link(campaign.sms_template),
            recipients_handed_off=handed,
            total_clicks=total,
            human_clicks=human,
            distinct_contacts_clicked=distinct,
            ctr_percent=_ctr(distinct, handed),
            carrier_distribution=carrier_dist,
            clickers=[
                sms_schemas.SmsClickerOut(
                    recipient_id=r.id,
                    contact_id=r.contact_id,
                    full_name=r.full_name_snapshot,
                    phone_masked=mask_phone(r.phone_normalized_snapshot),
                    carrier_bucket=r.carrier_bucket,
                    human_click_count=r.human_click_count,
                    first_human_clicked_at=r.first_human_clicked_at,
                    last_human_clicked_at=r.last_human_clicked_at,
                )
                for r in clickers
            ],
        )

    # ---------------------------------------------------------------
    # Opt-out admin (ghi tay + danh sách)
    # ---------------------------------------------------------------
    async def manual_opt_out(
        self, data: sms_schemas.SmsOptOutManualCreate, user
    ) -> sms_schemas.SmsOptOutOut:
        normalized, valid = normalize_and_validate_vietnam_phone(data.phone)
        if not valid or not normalized or not is_vietnam_mobile(normalized):
            raise ValidationError(
                detail="Số điện thoại di động không hợp lệ."
            )
        if await self.repo.get_opt_out(normalized) is not None:
            raise DuplicateResourceError(
                detail="Số này đã nằm trong danh sách từ chối."
            )
        row = await self.repo.create_opt_out(
            {
                "phone_normalized": normalized,
                "source": data.source,
                "source_reference": data.source_reference,
                "reason": data.reason,
                "revoked_by_id": getattr(user, "id", None),
                "observed_at": datetime.now(timezone.utc),
            }
        )
        return sms_schemas.SmsOptOutOut.model_validate(row)

    async def list_opt_outs(
        self,
        *,
        skip: int,
        limit: int,
        search: Optional[str] = None,
        source: Optional[str] = None,
    ) -> sms_schemas.SmsOptOutList:
        total, items = await self.repo.list_opt_outs(
            skip=skip, limit=limit, search=search, source=source
        )
        return sms_schemas.SmsOptOutList(total=total, items=items)
