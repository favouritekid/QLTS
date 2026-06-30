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
from typing import Dict, List, Optional, Sequence

from sqlalchemy import and_, func, or_, select, update
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
        # handed_off_at IS NULL: chỉ recipient CHƯA bàn giao → drift gate +
        # sinh file chỉ xét/ghi người chưa gửi. Tránh wedge: drift trên nhà
        # mạng ĐÃ bàn giao không chặn re-export nhà mạng khác đang failed.
        return (
            SmsCampaignRecipient.campaign_id == campaign_id,
            SmsCampaignRecipient.build_revision == revision,
            SmsCampaignRecipient.invalidated_at.is_(None),
            SmsCampaignRecipient.excluded_reason.is_(None),
            SmsCampaignRecipient.handed_off_at.is_(None),
        )

    async def get_exportable_recipients(
        self, campaign_id: int, revision: int, carrier_bucket: str
    ) -> List[SmsCampaignRecipient]:
        """Recipient sẽ ghi vào file của 1 nhà mạng — order id ổn định.

        Fail-closed TẠI THỜI ĐIỂM SINH FILE (đóng khe TOCTOU giữa gate
        pre-commit và sinh file post-commit sau khi nhả lock): chỉ lấy
        recipient mà contact VẪN consent 'granted' VÀ số CHƯA vào sms_opt_out.
        Recipient mất contact (contact_id NULL → INNER JOIN loại) cũng bị loại."""
        suppressed = select(SmsOptOut.phone_normalized)
        res = await self.db.execute(
            select(SmsCampaignRecipient)
            .join(
                SmsContact, SmsContact.id == SmsCampaignRecipient.contact_id
            )
            .where(
                *self._exportable_filter(campaign_id, revision),
                SmsCampaignRecipient.carrier_bucket == carrier_bucket,
                SmsContact.marketing_consent_status == "granted",
                SmsCampaignRecipient.phone_normalized_snapshot.notin_(
                    suppressed
                ),
            )
            .order_by(SmsCampaignRecipient.id)
        )
        return list(res.scalars().all())

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

    async def invalidate_export_batches_before(
        self, campaign_id: int, before_revision: int
    ) -> None:
        """Rebuild (revision mới) → vô hiệu MỌI export batch revision CŨ
        (pending/generated/failed) → status='invalidated' + invalidated_at.
        download check invalidated_at nên KHÔNG còn phục vụ file revision cũ
        (PII lỗi thời/consent đã đổi). KHÔNG đụng batch đã 'handed_off' (giữ
        audit; rebuild vốn đã bị chặn nếu có recipient handed_off)."""
        await self.db.execute(
            update(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.campaign_id == campaign_id,
                SmsCampaignExportBatch.build_revision < before_revision,
                SmsCampaignExportBatch.status.in_(
                    ("pending", "generated", "failed")
                ),
                SmsCampaignExportBatch.invalidated_at.is_(None),
            )
            .values(status="invalidated", invalidated_at=func.now())
        )

    async def list_purgeable_batches(
        self, now: datetime, limit: int = 500
    ) -> List[SmsCampaignExportBatch]:
        """Batch cần dọn file (purged_at NULL):
        (a) generated/handed_off đã quá `expires_at` (hết retention); HOẶC
        (b) failed/invalidated → dọn NGAY không phụ thuộc expires_at (file rác/
        ghi-dở hoặc revision cũ; batch failed luôn có expires_at=NULL nên KHÔNG
        thể gộp vào nhánh (a) — nếu không sẽ rò rỉ PII vĩnh viễn)."""
        res = await self.db.execute(
            select(SmsCampaignExportBatch)
            .where(
                SmsCampaignExportBatch.purged_at.is_(None),
                or_(
                    SmsCampaignExportBatch.status.in_(
                        ("failed", "invalidated")
                    ),
                    and_(
                        SmsCampaignExportBatch.status.in_(
                            ("generated", "handed_off")
                        ),
                        SmsCampaignExportBatch.expires_at.is_not(None),
                        SmsCampaignExportBatch.expires_at < now,
                    ),
                ),
            )
            .order_by(SmsCampaignExportBatch.id)
            .limit(limit)
            # FOR UPDATE SKIP LOCKED: giữ khoá khi cleanup ghi purged → không
            # lost-update với prepare_export đang re-export reset CÙNG batch;
            # batch đang bị re-export (đã khoá) thì cleanup BỎ QUA (skip).
            .with_for_update(skip_locked=True)
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
