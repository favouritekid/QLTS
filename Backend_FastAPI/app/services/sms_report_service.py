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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.sms_campaign_repository import SmsCampaignRepository
from app.repositories.sms_engagement_repository import SmsEngagementRepository
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
    # clamp ≤100% (an toàn; distinct ⊆ handed sau khi cùng population).
    if not handed_off:
        return 0.0
    return round(min(distinct_human, handed_off) / handed_off * 100, 2)


class SmsReportService:
    """Report click + dashboard + opt-out admin."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsTrackingRepository(db)
        self.campaign_repo = SmsCampaignRepository(db)
        self.engagement_repo = SmsEngagementRepository(db)

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
        scope = dict(campaign_id=campaign_id, carrier=carrier, group_id=group_id)
        # buckets = chuỗi thời gian (windowed theo date_from/date_to); totals +
        # CTR + handed = cấp campaign TOÀN THỜI → 3 con số reconcile, date CHỈ
        # ảnh hưởng buckets (#R3-3/#R3-5: bỏ query distinct lần 2).
        buckets = await self.repo.click_buckets(
            granularity=granularity,
            date_from=date_from,
            date_to=date_to,
            **scope,
        )
        total, human, distinct = await self.repo.click_totals(**scope)
        handed = await self.repo.count_handed_off(**scope)
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
        try:
            # SAVEPOINT: race 2 request // cùng số (admin double-submit hoặc đua
            # public landing opt-out) vượt check trên → UNIQUE phone vi phạm →
            # 409 sạch thay vì 500 + abort transaction ngoài (đối xứng
            # public_opt_out).
            async with self.db.begin_nested():
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
        except IntegrityError:
            raise DuplicateResourceError(
                detail="Số này đã nằm trong danh sách từ chối."
            )
        # Opt-out MỚI → vô hiệu export batch chưa bàn giao chứa số này (§8.4).
        await self.repo.invalidate_unhanded_exports_for_phone(normalized)
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

    # ---------------------------------------------------------------
    # Phase 2 (§16.7) — report ngành nóng + hồ sơ sở thích 1 contact
    # ---------------------------------------------------------------
    async def program_interest_report(
        self,
        *,
        campaign_id: Optional[int] = None,
        group_id: Optional[int] = None,
        major_program_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> sms_schemas.SmsProgramInterestReport:
        # LƯU Ý ĐO LƯỜNG (/review #4): total_dwell/view_count là tín hiệu THÔ do
        # client báo (đã lọc bot + clamp wall-clock/lượt + rate-limit per-IP);
        # 1 người có thể tự bơm dwell CHÍNH ngành mình quan tâm. Chấp nhận: chỉ
        # tự-ảnh-hưởng contact của họ, và tín hiệu xếp hạng cốt lõi per-contact
        # là interest_score (CÓ TRẦN normalize), không phải dwell thô của report.
        scope = dict(
            campaign_id=campaign_id,
            group_id=group_id,
            major_program_id=major_program_id,
            date_from=date_from,
            date_to=date_to,
        )
        rows = await self.engagement_repo.program_interest_report(**scope)
        distinct_total, view_total, dwell_total = (
            await self.engagement_repo.program_interest_totals(**scope)
        )
        return sms_schemas.SmsProgramInterestReport(
            items=[
                sms_schemas.SmsProgramInterestRow(
                    major_program_id=pid,
                    program_name=name or "(ngành đã xoá)",
                    distinct_contacts=distinct,
                    view_count=views,
                    total_dwell_seconds=dwell,
                    avg_dwell_seconds=(
                        round(dwell / views, 1) if views else 0.0
                    ),
                )
                for pid, name, distinct, views, dwell in rows
            ],
            distinct_contacts_total=distinct_total,
            view_count_total=view_total,
            total_dwell_seconds=dwell_total,
        )

    async def contact_interests(
        self, contact_id: int
    ) -> sms_schemas.SmsContactInterestList:
        rows = await self.engagement_repo.contact_interests(contact_id)
        return sms_schemas.SmsContactInterestList(
            contact_id=contact_id,
            items=[
                sms_schemas.SmsContactInterestRow(
                    major_program_id=r.major_program_id,
                    program_name=name or "(ngành đã xoá)",
                    view_count=r.view_count,
                    total_dwell_seconds=r.total_dwell_seconds,
                    interest_score=r.interest_score,
                    first_interest_at=r.first_interest_at,
                    last_interest_at=r.last_interest_at,
                )
                for r, name in rows
            ],
        )
