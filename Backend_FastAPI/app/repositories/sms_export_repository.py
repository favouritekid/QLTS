# app/repositories/sms_export_repository.py
"""
Data-access SMS export (PR-4): export-batch lifecycle (find-or-create idempotent
theo (campaign, revision, carrier), update generated/failed/handed_off/purged),
recipient EXPORTABLE per nhà mạng (để sinh Excel), re-check consent/suppression
drift fail-closed, và đánh dấu handed_off (recipient + contact freq-cap).

Standalone repository (giống sms_campaign_repository). Service flush, router
commit. Xem SMS_MARKETING_MODULE_DESIGN.md §8 / §11.7.
"""
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms import (
    SmsCampaignExportBatch,
    SmsCampaignRecipient,
    SmsContact,
    SmsContactGroup,
    SmsOptOut,
)


class SmsExportRepository:
    """Repository export-batch + recipient export + drift re-check + handoff."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_group_names(
        self, group_ids: Sequence[int]
    ) -> Dict[int, str]:
        """{group_id: tên nhóm} để dựng nhãn filename B2 (1 nhóm→tên; nhiều
        nhóm→'A+B+N'). Lấy tên kể cả nhóm đã ngừng hoạt động (nhãn = snapshot
        lựa chọn)."""
        if not group_ids:
            return {}
        res = await self.db.execute(
            select(SmsContactGroup.id, SmsContactGroup.name).where(
                SmsContactGroup.id.in_(set(group_ids))
            )
        )
        return {r[0]: r[1] for r in res.all()}

    # ---------------------------------------------------------------
    # Recipient EXPORTABLE (revision hiện tại, chưa invalidated, không bị loại)
    # ---------------------------------------------------------------
    def _exportable_filter(self, campaign_id: int, revision: int):
        return (
            SmsCampaignRecipient.campaign_id == campaign_id,
            SmsCampaignRecipient.build_revision == revision,
            SmsCampaignRecipient.invalidated_at.is_(None),
            SmsCampaignRecipient.excluded_reason.is_(None),
        )

    async def get_exportable_recipients(
        self, campaign_id: int, revision: int, carrier_bucket: str
    ) -> List[SmsCampaignRecipient]:
        """Recipient sẽ ghi vào file của 1 nhà mạng — order id ổn định."""
        res = await self.db.execute(
            select(SmsCampaignRecipient)
            .where(
                *self._exportable_filter(campaign_id, revision),
                SmsCampaignRecipient.carrier_bucket == carrier_bucket,
            )
            .order_by(SmsCampaignRecipient.id)
        )
        return list(res.scalars().all())

    async def counts_by_carrier_exportable(
        self, campaign_id: int, revision: int
    ) -> List[Tuple[str, int]]:
        """(carrier_bucket, count) cho recipient exportable — mỗi carrier 1 file."""
        res = await self.db.execute(
            select(SmsCampaignRecipient.carrier_bucket, func.count())
            .where(*self._exportable_filter(campaign_id, revision))
            .group_by(SmsCampaignRecipient.carrier_bucket)
            .order_by(SmsCampaignRecipient.carrier_bucket)
        )
        return [(r[0], int(r[1])) for r in res.all()]

    async def count_over_limit(self, campaign_id: int, revision: int) -> int:
        """Số recipient bị loại VÌ over_limit (gate export chặn nếu >0, §8.4)."""
        res = await self.db.scalar(
            select(func.count())
            .select_from(SmsCampaignRecipient)
            .where(
                SmsCampaignRecipient.campaign_id == campaign_id,
                SmsCampaignRecipient.build_revision == revision,
                SmsCampaignRecipient.invalidated_at.is_(None),
                SmsCampaignRecipient.excluded_reason == "over_limit",
            )
        )
        return int(res or 0)

    # ---------------------------------------------------------------
    # Re-check consent/suppression FRESH ngay trước export (fail-closed §8.4)
    # ---------------------------------------------------------------
    async def count_lost_consent(self, campaign_id: int, revision: int) -> int:
        """Recipient exportable mà contact ĐÃ mất consent (revoked/unknown) hoặc
        contact bị xoá (contact_id NULL → consent không xác định được)."""
        res = await self.db.scalar(
            select(func.count())
            .select_from(SmsCampaignRecipient)
            .outerjoin(
                SmsContact, SmsContact.id == SmsCampaignRecipient.contact_id
            )
            .where(
                *self._exportable_filter(campaign_id, revision),
                (SmsContact.id.is_(None))
                | (SmsContact.marketing_consent_status != "granted"),
            )
        )
        return int(res or 0)

    async def count_new_suppression(
        self, campaign_id: int, revision: int
    ) -> int:
        """Recipient exportable mà số ĐÃ vào sms_opt_out (opt-out/DNC) sau build."""
        suppressed = select(SmsOptOut.phone_normalized)
        res = await self.db.scalar(
            select(func.count())
            .select_from(SmsCampaignRecipient)
            .where(
                *self._exportable_filter(campaign_id, revision),
                SmsCampaignRecipient.phone_normalized_snapshot.in_(suppressed),
            )
        )
        return int(res or 0)

    # ---------------------------------------------------------------
    # Export batch lifecycle
    # ---------------------------------------------------------------
    async def get_batch_for_carrier_locked(
        self, campaign_id: int, revision: int, carrier_bucket: str
    ) -> Optional[SmsCampaignExportBatch]:
        """Lock batch (campaign, revision, carrier) — find-or-create idempotent.
        Concurrent caller gom về cùng row qua UNIQUE + FOR UPDATE."""
        res = await self.db.execute(
            select(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.campaign_id == campaign_id,
                SmsCampaignExportBatch.build_revision == revision,
                SmsCampaignExportBatch.carrier_bucket == carrier_bucket,
            )
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def create_batch(self, fields: dict) -> SmsCampaignExportBatch:
        batch = SmsCampaignExportBatch(**fields)
        self.db.add(batch)
        await self.db.flush()
        return batch

    async def get_batch(
        self, batch_id: int
    ) -> Optional[SmsCampaignExportBatch]:
        res = await self.db.execute(
            select(SmsCampaignExportBatch).where(
                SmsCampaignExportBatch.id == batch_id
            )
        )
        return res.scalars().first()

    async def get_batch_for_update(
        self, batch_id: int
    ) -> Optional[SmsCampaignExportBatch]:
        res = await self.db.execute(
            select(SmsCampaignExportBatch)
            .where(SmsCampaignExportBatch.id == batch_id)
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def list_batches(
        self, campaign_id: int, revision: int
    ) -> List[SmsCampaignExportBatch]:
        res = await self.db.execute(
            select(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.campaign_id == campaign_id,
                SmsCampaignExportBatch.build_revision == revision,
            )
            .order_by(SmsCampaignExportBatch.carrier_bucket)
        )
        return list(res.scalars().all())

    async def list_purgeable_batches(
        self, now: datetime, limit: int = 500
    ) -> List[SmsCampaignExportBatch]:
        """Batch còn file (generated/handed_off/failed) đã quá expires_at →
        cleanup job xoá file + set purged. failed cũng dọn temp nếu sót."""
        res = await self.db.execute(
            select(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.status.in_(
                    ("generated", "handed_off", "failed")
                ),
                SmsCampaignExportBatch.purged_at.is_(None),
                SmsCampaignExportBatch.expires_at.is_not(None),
                SmsCampaignExportBatch.expires_at < now,
            )
            .order_by(SmsCampaignExportBatch.id)
            .limit(limit)
        )
        return list(res.scalars().all())

    # ---------------------------------------------------------------
    # Handed-off: recipient + contact freq-cap proxy
    # ---------------------------------------------------------------
    async def mark_recipients_handed_off(
        self, campaign_id: int, revision: int, carrier_bucket: str, now: datetime
    ) -> Sequence[int]:
        """Set handed_off_at cho recipient exportable của batch → chặn rebuild
        (has_handed_off_recipients) + neo freq-cap. Trả contact_id liên quan."""
        res = await self.db.execute(
            update(SmsCampaignRecipient)
            .where(
                *self._exportable_filter(campaign_id, revision),
                SmsCampaignRecipient.carrier_bucket == carrier_bucket,
                SmsCampaignRecipient.handed_off_at.is_(None),
            )
            .values(handed_off_at=now)
            .returning(SmsCampaignRecipient.contact_id)
        )
        return [r[0] for r in res.all() if r[0] is not None]

    async def touch_contacts_handed_off(
        self, contact_ids: Sequence[int], now: datetime
    ) -> None:
        """Cập nhật last_handed_off_at (frequency-cap proxy §4.2) cho contact
        vừa bàn giao."""
        if not contact_ids:
            return
        await self.db.execute(
            update(SmsContact)
            .where(SmsContact.id.in_(set(contact_ids)))
            .values(last_handed_off_at=now)
        )

    async def count_unhanded_batches(
        self, campaign_id: int, revision: int
    ) -> int:
        """Số batch của revision CHƯA bàn giao (status != handed_off) — để
        chuyển campaign sang 'closed' khi tất cả nhà mạng đã bàn giao."""
        res = await self.db.scalar(
            select(func.count())
            .select_from(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.campaign_id == campaign_id,
                SmsCampaignExportBatch.build_revision == revision,
                SmsCampaignExportBatch.status != "handed_off",
            )
        )
        return int(res or 0)
