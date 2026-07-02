# app/repositories/sms_tracking_repository.py
"""
Data-access SMS tracking/landing/reports/opt-out (PR-5): resolve token_hash →
recipient+campaign, ghi click event + cập nhật denorm counter (atomic), tra
opt-out, report click theo granularity (JOIN click↔recipient), dashboard CTR,
và admin opt-out list/insert.

Standalone repository. Service flush, router commit. Xem
SMS_MARKETING_MODULE_DESIGN.md §6/§9/§19.
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.sms import (
    SmsCampaign,
    SmsCampaignExportBatch,
    SmsCampaignRecipient,
    SmsClickEvent,
    SmsConsultLink,
    SmsOptOut,
)


class SmsTrackingRepository:
    """Repository resolve + click + opt-out + report + dashboard."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------
    # Resolve token_hash → recipient + campaign (cho /r/ và landing)
    # ---------------------------------------------------------------
    async def lookup_by_token_hash(
        self, token_hash: str
    ) -> Optional[Tuple[SmsCampaignRecipient, SmsCampaign]]:
        """(recipient, campaign) nếu token_hash khớp recipient CHƯA invalidated;
        None nếu không thấy/đã invalidated. JOIN campaign để quyết định redirect/
        landing."""
        res = await self.db.execute(
            select(SmsCampaignRecipient, SmsCampaign)
            .join(SmsCampaign, SmsCampaign.id == SmsCampaignRecipient.campaign_id)
            .where(
                SmsCampaignRecipient.token_hash == token_hash,
                SmsCampaignRecipient.invalidated_at.is_(None),
            )
            .limit(1)
        )
        row = res.first()
        return (row[0], row[1]) if row else None

    # ---------------------------------------------------------------
    # Consult link resolve + click (P2-3 — nhánh 2 của /r/{code})
    # ---------------------------------------------------------------
    async def lookup_consult_by_token_hash(
        self, token_hash: str
    ) -> Optional[SmsConsultLink]:
        """SmsConsultLink nếu token_hash khớp; None nếu không. Dùng khi
        recipient lookup KHÔNG thấy (resolve mở rộng §16.7)."""
        res = await self.db.execute(
            select(SmsConsultLink)
            .where(SmsConsultLink.token_hash == token_hash)
            .limit(1)
        )
        return res.scalars().first()

    async def record_consult_click(
        self,
        *,
        consult_link_id: int,
        ip_hash: Optional[str],
        user_agent: Optional[str],
        is_bot: bool,
        bot_reason: Optional[str],
        now: datetime,
    ) -> None:
        """Ghi click cho consult link — đối xứng record_click recipient. Không
        có sms_click_event cho consult (event gắn recipient_id) → chỉ counter
        denorm atomic trên consult_link."""
        inc_human = 0 if is_bot else 1
        values = {
            "raw_click_count": SmsConsultLink.raw_click_count + 1,
            "human_click_count": (
                SmsConsultLink.human_click_count + inc_human
            ),
        }
        if not is_bot:
            values["last_human_clicked_at"] = now
            values["first_human_clicked_at"] = case(
                (SmsConsultLink.first_human_clicked_at.is_(None), now),
                else_=SmsConsultLink.first_human_clicked_at,
            )
        await self.db.execute(
            update(SmsConsultLink)
            .where(SmsConsultLink.id == consult_link_id)
            .values(**values)
        )

    # ---------------------------------------------------------------
    # Click event + denorm counter (atomic — chống lost update khi click //)
    # ---------------------------------------------------------------
    async def record_click(
        self,
        *,
        recipient_id: int,
        ip_hash: Optional[str],
        user_agent: Optional[str],
        is_bot: bool,
        bot_reason: Optional[str],
        now: datetime,
    ) -> None:
        self.db.add(
            SmsClickEvent(
                recipient_id=recipient_id,
                ip_hash=ip_hash,
                # Cắt ≤512 khớp cột String(512) — UA dài (bot/client gửi >512)
                # sẽ StringDataRightTruncation → /r/ 500 thay vì 302.
                user_agent=(user_agent[:512] if user_agent else None),
                is_suspected_bot=is_bot,
                bot_reason=bot_reason,
            )
        )
        # UPDATE atomic (counter = counter + 1) → không read-modify-write nên
        # nhiều click đồng thời không mất đếm. human + first/last chỉ khi non-bot.
        inc_human = 0 if is_bot else 1
        values = {
            "raw_click_count": SmsCampaignRecipient.raw_click_count + 1,
            "human_click_count": (
                SmsCampaignRecipient.human_click_count + inc_human
            ),
        }
        if not is_bot:
            values["last_human_clicked_at"] = now
            values["first_human_clicked_at"] = case(
                (
                    SmsCampaignRecipient.first_human_clicked_at.is_(None),
                    now,
                ),
                else_=SmsCampaignRecipient.first_human_clicked_at,
            )
        await self.db.execute(
            update(SmsCampaignRecipient)
            .where(SmsCampaignRecipient.id == recipient_id)
            .values(**values)
        )

    # ---------------------------------------------------------------
    # Opt-out
    # ---------------------------------------------------------------
    async def get_contact_phone(self, contact_id: int) -> Optional[str]:
        """phone_normalized của 1 contact (consult resolve — recipient dùng
        snapshot; consult phải tra contact). None nếu contact đã xoá."""
        from app.models.sms import SmsContact
        return await self.db.scalar(
            select(SmsContact.phone_normalized).where(
                SmsContact.id == contact_id
            )
        )

    async def is_phone_opted_out(self, phone_normalized: str) -> bool:
        res = await self.db.scalar(
            select(SmsOptOut.id)
            .where(SmsOptOut.phone_normalized == phone_normalized)
            .limit(1)
        )
        return res is not None

    async def get_opt_out(self, phone_normalized: str) -> Optional[SmsOptOut]:
        res = await self.db.execute(
            select(SmsOptOut).where(
                SmsOptOut.phone_normalized == phone_normalized
            )
        )
        return res.scalars().first()

    async def create_opt_out(self, fields: dict) -> SmsOptOut:
        row = SmsOptOut(**fields)
        self.db.add(row)
        await self.db.flush()
        return row

    async def invalidate_unhanded_exports_for_phone(
        self, phone_normalized: str
    ) -> None:
        """Khi 1 số opt-out: vô hiệu export batch (pending/generated, chưa bàn
        giao, chưa invalidated) CÓ CHỨA số này ở revision của batch → file XLSX
        cũ chứa số đã suppress KHÔNG còn tải/bàn giao được (download +
        mark-handed-off chặn invalidated_at); admin export lại sẽ re-check
        suppression và loại số. §8.4 (suppression đổi sau export, trước handoff)."""
        has_suppressed_recipient = (
            select(SmsCampaignRecipient.id)
            .where(
                SmsCampaignRecipient.campaign_id
                == SmsCampaignExportBatch.campaign_id,
                SmsCampaignRecipient.build_revision
                == SmsCampaignExportBatch.build_revision,
                SmsCampaignRecipient.carrier_bucket
                == SmsCampaignExportBatch.carrier_bucket,
                SmsCampaignRecipient.phone_normalized_snapshot
                == phone_normalized,
                SmsCampaignRecipient.excluded_reason.is_(None),
                SmsCampaignRecipient.invalidated_at.is_(None),
                SmsCampaignRecipient.handed_off_at.is_(None),
            )
            .exists()
        )
        await self.db.execute(
            update(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.status.in_(("pending", "generated")),
                SmsCampaignExportBatch.invalidated_at.is_(None),
                has_suppressed_recipient,
            )
            .values(status="invalidated", invalidated_at=func.now())
        )

    async def list_opt_outs(
        self,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Tuple[int, List[SmsOptOut]]:
        conds = []
        if source:
            conds.append(SmsOptOut.source == source)
        if search:
            conds.append(
                SmsOptOut.phone_normalized.ilike(f"%{search.strip()}%")
            )
        base = select(SmsOptOut)
        if conds:
            base = base.where(*conds)
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsOptOut.observed_at.desc()).offset(skip).limit(limit)
        )
        return int(total or 0), list(res.scalars().all())

    # ---------------------------------------------------------------
    # Reports — click theo granularity (§9)
    # ---------------------------------------------------------------
    def _click_filters(
        self,
        *,
        campaign_id: Optional[int] = None,
        carrier: Optional[str] = None,
        group_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ):
        # Tử số click chỉ tính trên recipient handed-off (cùng quần thể mẫu số
        # CTR) → ctr ≤ 100%, không đếm click trước-handoff/revision cũ (#6).
        conds = list(self._handed_off_population())
        if campaign_id is not None:
            conds.append(SmsCampaignRecipient.campaign_id == campaign_id)
        if carrier:
            conds.append(SmsCampaignRecipient.carrier_bucket == carrier)
        if group_id is not None:
            # GIN: group_ids_snapshot @> ARRAY[gid]
            conds.append(
                SmsCampaignRecipient.group_ids_snapshot.contains([group_id])
            )
        if date_from is not None:
            conds.append(SmsClickEvent.clicked_at >= date_from)
        if date_to is not None:
            conds.append(SmsClickEvent.clicked_at <= date_to)
        return conds

    def _handed_off_population(self):
        """Quần thể CTR (mẫu số): recipient ĐÃ bàn giao + exportable + chưa
        invalidated → dùng CHUNG cho tử (click) lẫn mẫu (handed_off) để CTR ≤
        100% và không đếm trùng qua revision."""
        return (
            SmsCampaignRecipient.handed_off_at.is_not(None),
            SmsCampaignRecipient.excluded_reason.is_(None),
            SmsCampaignRecipient.invalidated_at.is_(None),
        )

    async def click_buckets(
        self, *, granularity: str, **filters
    ) -> List[Tuple[datetime, int, int, int]]:
        """(period, total, human, distinct_human_recipients) theo bucket."""
        conds = self._click_filters(**filters)
        # Bucket theo GIỜ VN (AT TIME ZONE settings.TIMEZONE) — không UTC: click
        # 00:00–07:00 giờ VN không bị rớt sang ngày hôm trước (#R3-4).
        bucket = func.date_trunc(
            granularity,
            func.timezone(settings.TIMEZONE, SmsClickEvent.clicked_at),
        )
        human = case((SmsClickEvent.is_suspected_bot.is_(False), 1), else_=0)
        # distinct theo PHONE (không recipient_id): 1 người ở nhiều campaign/
        # revision không bị đếm nhiều lần ở report cross-campaign (#10).
        distinct_human = func.count(
            func.distinct(
                case(
                    (
                        SmsClickEvent.is_suspected_bot.is_(False),
                        SmsCampaignRecipient.phone_normalized_snapshot,
                    ),
                    else_=None,
                )
            )
        )
        res = await self.db.execute(
            select(
                bucket.label("period"),
                func.count().label("total"),
                func.coalesce(func.sum(human), 0).label("human"),
                distinct_human.label("distinct_human"),
            )
            .select_from(SmsClickEvent)
            .join(
                SmsCampaignRecipient,
                SmsCampaignRecipient.id == SmsClickEvent.recipient_id,
            )
            .where(*conds)
            .group_by(bucket)
            .order_by(bucket)
        )
        return [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in res.all()]

    async def click_totals(self, **filters) -> Tuple[int, int, int]:
        """(total_clicks, human_clicks, distinct_human_recipients) toàn dải."""
        conds = self._click_filters(**filters)
        human = case((SmsClickEvent.is_suspected_bot.is_(False), 1), else_=0)
        # distinct theo PHONE (không recipient_id): 1 người ở nhiều campaign/
        # revision không bị đếm nhiều lần ở report cross-campaign (#10).
        distinct_human = func.count(
            func.distinct(
                case(
                    (
                        SmsClickEvent.is_suspected_bot.is_(False),
                        SmsCampaignRecipient.phone_normalized_snapshot,
                    ),
                    else_=None,
                )
            )
        )
        res = await self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(human), 0),
                distinct_human,
            )
            .select_from(SmsClickEvent)
            .join(
                SmsCampaignRecipient,
                SmsCampaignRecipient.id == SmsClickEvent.recipient_id,
            )
            .where(*conds)
        )
        r = res.first()
        return int(r[0]), int(r[1]), int(r[2])

    async def count_handed_off(
        self,
        *,
        campaign_id: Optional[int] = None,
        carrier: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> int:
        """Mẫu số CTR: số NGƯỜI (distinct phone) đã bàn giao + exportable +
        chưa invalidated. distinct phone (không recipient-row) để KHỚP đơn vị
        tử số (distinct phone clicked) → CTR cross-campaign không lệch (#R3-1)."""
        conds = list(self._handed_off_population())
        if campaign_id is not None:
            conds.append(SmsCampaignRecipient.campaign_id == campaign_id)
        if carrier:
            conds.append(SmsCampaignRecipient.carrier_bucket == carrier)
        if group_id is not None:
            conds.append(
                SmsCampaignRecipient.group_ids_snapshot.contains([group_id])
            )
        res = await self.db.scalar(
            select(
                func.count(
                    func.distinct(SmsCampaignRecipient.phone_normalized_snapshot)
                )
            )
            .select_from(SmsCampaignRecipient)
            .where(*conds)
        )
        return int(res or 0)

    # ---------------------------------------------------------------
    # Dashboard campaign (§9)
    # ---------------------------------------------------------------
    async def carrier_distribution_handed_off(
        self, campaign_id: int
    ) -> Dict[str, int]:
        res = await self.db.execute(
            select(SmsCampaignRecipient.carrier_bucket, func.count())
            .where(
                SmsCampaignRecipient.campaign_id == campaign_id,
                *self._handed_off_population(),
            )
            .group_by(SmsCampaignRecipient.carrier_bucket)
        )
        return {r[0]: int(r[1]) for r in res.all()}

    async def top_clickers(
        self, campaign_id: int, limit: int = 100
    ) -> List[SmsCampaignRecipient]:
        """Recipient đã click (non-bot) của campaign — sắp theo lượt click giảm
        dần. Lọc cùng population handed-off (#R3-2) → khớp totals/CTR ở dashboard
        (không liệt kê clicker của recipient chưa-handoff/đã-invalidated)."""
        res = await self.db.execute(
            select(SmsCampaignRecipient)
            .where(
                SmsCampaignRecipient.campaign_id == campaign_id,
                SmsCampaignRecipient.human_click_count > 0,
                *self._handed_off_population(),
            )
            .order_by(
                SmsCampaignRecipient.human_click_count.desc(),
                SmsCampaignRecipient.last_human_clicked_at.desc(),
            )
            .limit(limit)
        )
        return list(res.scalars().all())
