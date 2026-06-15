# app/repositories/sms_campaign_repository.py
"""
Data-access SMS campaign domain (PR-3): campaign CRUD, campaign↔group,
nguồn build (members-of-groups, opt-out, carrier prefix map), recipient
bulk-insert + invalidate-old-revision, và aggregate cho preflight.

Standalone repository (giống sms_contact_repository). Service flush, router
commit. Xem SMS_MARKETING_MODULE_DESIGN.md §3/§6/§7/§8.
"""
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms import (
    SmsCampaign,
    SmsCampaignGroup,
    SmsCampaignRecipient,
    SmsContact,
    SmsContactGroup,
    SmsContactGroupMember,
    SmsOptOut,
    SmsPrefixCarrierRule,
)


class SmsCampaignRepository:
    """Repository campaign + recipient build + preflight."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------
    # Campaign
    # ---------------------------------------------------------------
    async def create_campaign(self, data: dict) -> SmsCampaign:
        campaign = SmsCampaign(**data)
        self.db.add(campaign)
        await self.db.flush()
        return campaign

    async def get_campaign(self, campaign_id: int) -> Optional[SmsCampaign]:
        res = await self.db.execute(
            select(SmsCampaign).where(SmsCampaign.id == campaign_id)
        )
        return res.scalars().first()

    async def get_campaign_for_update(
        self, campaign_id: int
    ) -> Optional[SmsCampaign]:
        """Lock campaign row — build/attestation cập nhật build_revision."""
        res = await self.db.execute(
            select(SmsCampaign)
            .where(SmsCampaign.id == campaign_id)
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def get_campaign_by_code(
        self, code: str
    ) -> Optional[SmsCampaign]:
        res = await self.db.execute(
            select(SmsCampaign).where(SmsCampaign.code == code)
        )
        return res.scalars().first()

    async def list_campaigns(
        self,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[int, List[SmsCampaign]]:
        conds = []
        if status is not None:
            conds.append(SmsCampaign.status == status)
        if search:
            like = f"%{search.strip()}%"
            conds.append(
                or_(
                    SmsCampaign.name.ilike(like),
                    SmsCampaign.code.ilike(like),
                )
            )
        base = select(SmsCampaign)
        if conds:
            base = base.where(*conds)
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsCampaign.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return int(total or 0), list(res.scalars().all())

    # ---------------------------------------------------------------
    # Campaign ↔ group
    # ---------------------------------------------------------------
    async def get_campaign_group(
        self, campaign_id: int, group_id: int
    ) -> Optional[SmsCampaignGroup]:
        res = await self.db.execute(
            select(SmsCampaignGroup).where(
                SmsCampaignGroup.campaign_id == campaign_id,
                SmsCampaignGroup.group_id == group_id,
            )
        )
        return res.scalars().first()

    async def create_campaign_group(
        self, campaign_id: int, group_id: int
    ) -> SmsCampaignGroup:
        cg = SmsCampaignGroup(campaign_id=campaign_id, group_id=group_id)
        self.db.add(cg)
        await self.db.flush()
        return cg

    async def delete_campaign_group(self, cg: SmsCampaignGroup) -> None:
        await self.db.delete(cg)
        await self.db.flush()

    async def get_campaign_group_ids(self, campaign_id: int) -> List[int]:
        res = await self.db.execute(
            select(SmsCampaignGroup.group_id)
            .where(SmsCampaignGroup.campaign_id == campaign_id)
            .order_by(SmsCampaignGroup.group_id)
        )
        return [r[0] for r in res.all()]

    async def get_group_counts(
        self, campaign_ids: Sequence[int]
    ) -> Dict[int, int]:
        """{campaign_id: số nhóm} cho list (tránh group_count=null ở list API)."""
        if not campaign_ids:
            return {}
        res = await self.db.execute(
            select(SmsCampaignGroup.campaign_id, func.count())
            .where(SmsCampaignGroup.campaign_id.in_(set(campaign_ids)))
            .group_by(SmsCampaignGroup.campaign_id)
        )
        return {r[0]: int(r[1]) for r in res.all()}

    # ---------------------------------------------------------------
    # Build inputs
    # ---------------------------------------------------------------
    async def get_members_of_groups(
        self, group_ids: Sequence[int]
    ) -> List[Tuple[int, SmsContact]]:
        """(group_id, contact) cho member của các nhóm đã chọn — CHỈ nhóm
        is_active (nhóm đã ngừng KHÔNG đóng góp recipient, kể cả khi bị tắt
        sau attach). Service dedupe theo phone + gom group_ids đóng góp."""
        if not group_ids:
            return []
        res = await self.db.execute(
            select(SmsContactGroupMember.group_id, SmsContact)
            .join(
                SmsContact,
                SmsContact.id == SmsContactGroupMember.contact_id,
            )
            .join(
                SmsContactGroup,
                SmsContactGroup.id == SmsContactGroupMember.group_id,
            )
            .where(
                SmsContactGroupMember.group_id.in_(set(group_ids)),
                SmsContactGroup.is_active.is_(True),
            )
        )
        return [(row[0], row[1]) for row in res.all()]

    async def get_optout_source_map(
        self, phones: Sequence[str]
    ) -> Dict[str, str]:
        """{phone_normalized: source} cho số trong sms_opt_out (suppression
        toàn cục). source phân biệt opt-out người dùng (landing/manual/sms_reply
        /phone_call) vs `external_suppression` (DNC list) → service map
        excluded_reason đúng (opted_out vs dnc_suppressed). phone UNIQUE → 1
        row/phone."""
        if not phones:
            return {}
        res = await self.db.execute(
            select(SmsOptOut.phone_normalized, SmsOptOut.source).where(
                SmsOptOut.phone_normalized.in_(set(phones))
            )
        )
        return {r[0]: r[1] for r in res.all()}

    async def get_active_carrier_prefix_map(self) -> Dict[str, str]:
        res = await self.db.execute(
            select(
                SmsPrefixCarrierRule.prefix,
                SmsPrefixCarrierRule.carrier_code,
            ).where(SmsPrefixCarrierRule.is_active.is_(True))
        )
        return {r[0]: r[1] for r in res.all()}

    async def has_handed_off_recipients(self, campaign_id: int) -> bool:
        """True nếu ≥1 recipient của campaign đã bàn giao (handed_off_at NOT
        NULL) — chặn rebuild sau partial handoff (§232: chỉ rebuild khi CHƯA
        có batch bàn giao)."""
        res = await self.db.scalar(
            select(SmsCampaignRecipient.id)
            .where(
                SmsCampaignRecipient.campaign_id == campaign_id,
                SmsCampaignRecipient.handed_off_at.is_not(None),
            )
            .limit(1)
        )
        return res is not None

    # ---------------------------------------------------------------
    # Recipients
    # ---------------------------------------------------------------
    async def invalidate_recipients_before(
        self, campaign_id: int, before_revision: int
    ) -> None:
        """Vô hiệu recipient revision CŨ (chưa bàn giao) khi rebuild (§4.8)."""
        await self.db.execute(
            update(SmsCampaignRecipient)
            .where(
                SmsCampaignRecipient.campaign_id == campaign_id,
                SmsCampaignRecipient.build_revision < before_revision,
                SmsCampaignRecipient.invalidated_at.is_(None),
                SmsCampaignRecipient.handed_off_at.is_(None),
            )
            .values(invalidated_at=func.now())
        )

    async def bulk_insert_recipients(self, rows: List[dict]) -> None:
        """Core multi-row INSERT (KHÔNG ORM instance) → savepoint rollback
        sạch khi token collision retry (không để instance lingering)."""
        if not rows:
            return
        await self.db.execute(insert(SmsCampaignRecipient), rows)

    # ---------------------------------------------------------------
    # Preflight aggregates (build_revision hiện tại, invalidated_at NULL)
    # ---------------------------------------------------------------
    def _rev_filter(self, campaign_id: int, revision: int):
        return (
            SmsCampaignRecipient.campaign_id == campaign_id,
            SmsCampaignRecipient.build_revision == revision,
            SmsCampaignRecipient.invalidated_at.is_(None),
        )

    async def counts_by_excluded_reason(
        self, campaign_id: int, revision: int
    ) -> List[Tuple[Optional[str], int]]:
        """(excluded_reason|None, count) — None = exportable."""
        res = await self.db.execute(
            select(SmsCampaignRecipient.excluded_reason, func.count())
            .where(*self._rev_filter(campaign_id, revision))
            .group_by(SmsCampaignRecipient.excluded_reason)
        )
        return [(r[0], int(r[1])) for r in res.all()]

    async def counts_by_carrier_exportable(
        self, campaign_id: int, revision: int
    ) -> Dict[str, int]:
        res = await self.db.execute(
            select(SmsCampaignRecipient.carrier_bucket, func.count())
            .where(
                *self._rev_filter(campaign_id, revision),
                SmsCampaignRecipient.excluded_reason.is_(None),
            )
            .group_by(SmsCampaignRecipient.carrier_bucket)
        )
        return {r[0]: int(r[1]) for r in res.all()}

    async def get_over_limit_rows(
        self, campaign_id: int, revision: int, limit: int = 200
    ) -> List[SmsCampaignRecipient]:
        """CHỈ row bị loại CHÍNH VÌ over_limit (excluded_reason='over_limit')
        — nhất quán với excluded_by_reason['over_limit'] + warning. Row vừa
        over vừa no_consent/opted_out đã loại vì lý do ưu tiên cao hơn nên
        KHÔNG liệt kê (tránh báo cáo tự mâu thuẫn: list≠count)."""
        res = await self.db.execute(
            select(SmsCampaignRecipient)
            .where(
                *self._rev_filter(campaign_id, revision),
                SmsCampaignRecipient.excluded_reason == "over_limit",
            )
            .order_by(SmsCampaignRecipient.id)  # ổn định để phát hiện cắt
            .limit(limit)
        )
        return list(res.scalars().all())

    async def get_sample_skeletons(
        self, campaign_id: int, revision: int, limit: int = 5
    ) -> List[str]:
        """≤N skeleton của recipient EXPORTABLE (excluded_reason NULL) cho
        preview preflight (§D6 "5 dòng mẫu từ chính segment")."""
        res = await self.db.execute(
            select(SmsCampaignRecipient.rendered_message_skeleton)
            .where(
                *self._rev_filter(campaign_id, revision),
                SmsCampaignRecipient.excluded_reason.is_(None),
            )
            .order_by(SmsCampaignRecipient.id)
            .limit(limit)
        )
        return [r[0] for r in res.all() if r[0]]

    async def list_recipients(
        self, campaign_id: int, revision: int, skip: int = 0, limit: int = 50
    ) -> Tuple[int, List[SmsCampaignRecipient]]:
        base = select(SmsCampaignRecipient).where(
            *self._rev_filter(campaign_id, revision)
        )
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsCampaignRecipient.id).offset(skip).limit(limit)
        )
        return int(total or 0), list(res.scalars().all())
