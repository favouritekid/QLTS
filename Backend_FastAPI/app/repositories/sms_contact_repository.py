# app/repositories/sms_contact_repository.py
"""
Data-access cho SMS Marketing contact domain (PR-2): group, contact,
membership, consent-event ledger, import batch.

Standalone repository (KHÔNG kế thừa BaseRepository — model SMS không có
`deleted_at` và không cần `get_filtered` abstract). Mọi method async, dùng
`select()` + `selectinload`/`func.count`. Projection consent cập nhật dưới
row lock (`get_contact_for_update`). Service gọi `flush`, router `commit`.
"""
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms import (
    SmsContact,
    SmsContactGroup,
    SmsContactGroupMember,
    SmsContactImportBatch,
    SmsMarketingConsentEvent,
)


class SmsContactRepository:
    """Repository cho contact group/contact/membership/consent/import."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------
    # Contact group
    # ---------------------------------------------------------------
    async def create_group(self, data: dict) -> SmsContactGroup:
        group = SmsContactGroup(**data)
        self.db.add(group)
        await self.db.flush()
        return group

    async def get_group(self, group_id: int) -> Optional[SmsContactGroup]:
        res = await self.db.execute(
            select(SmsContactGroup).where(SmsContactGroup.id == group_id)
        )
        return res.scalars().first()

    async def get_group_by_code(
        self, code: str
    ) -> Optional[SmsContactGroup]:
        res = await self.db.execute(
            select(SmsContactGroup).where(SmsContactGroup.code == code)
        )
        return res.scalars().first()

    async def get_groups_by_ids(
        self, group_ids: Sequence[int]
    ) -> List[SmsContactGroup]:
        """Lấy các nhóm theo danh sách id (giữ thứ tự tên) — cho endpoint
        list nhóm đã gắn của campaign. Tránh N+1 (1 query IN)."""
        if not group_ids:
            return []
        res = await self.db.execute(
            select(SmsContactGroup)
            .where(SmsContactGroup.id.in_(set(group_ids)))
            .order_by(SmsContactGroup.name)
        )
        return list(res.scalars().all())

    async def list_groups(
        self,
        skip: int = 0,
        limit: int = 50,
        group_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[int, List[SmsContactGroup]]:
        conds = []
        if group_type is not None:
            conds.append(SmsContactGroup.group_type == group_type)
        if is_active is not None:
            conds.append(SmsContactGroup.is_active == is_active)
        if search:
            like = f"%{search.strip()}%"
            conds.append(
                or_(
                    SmsContactGroup.name.ilike(like),
                    SmsContactGroup.code.ilike(like),
                )
            )
        base = select(SmsContactGroup)
        if conds:
            base = base.where(*conds)
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsContactGroup.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return int(total or 0), list(res.scalars().all())

    async def count_members_by_group(
        self, group_ids: Sequence[int]
    ) -> Dict[int, int]:
        """Đếm thành viên cho nhiều nhóm 1 query (anti-N+1)."""
        if not group_ids:
            return {}
        res = await self.db.execute(
            select(
                SmsContactGroupMember.group_id, func.count()
            )
            .where(SmsContactGroupMember.group_id.in_(group_ids))
            .group_by(SmsContactGroupMember.group_id)
        )
        return {row[0]: int(row[1]) for row in res.all()}

    # ---------------------------------------------------------------
    # Contact
    # ---------------------------------------------------------------
    async def create_contact(self, data: dict) -> SmsContact:
        contact = SmsContact(**data)
        self.db.add(contact)
        await self.db.flush()
        return contact

    async def get_contact(self, contact_id: int) -> Optional[SmsContact]:
        res = await self.db.execute(
            select(SmsContact).where(SmsContact.id == contact_id)
        )
        return res.scalars().first()

    async def get_contact_for_update(
        self, contact_id: int
    ) -> Optional[SmsContact]:
        """Lock row contact (FOR UPDATE) trước khi cập nhật projection
        consent — chặn race 2 consent-event ghi latest-state lẫn nhau."""
        res = await self.db.execute(
            select(SmsContact)
            .where(SmsContact.id == contact_id)
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def lock_contacts_by_ids(
        self, contact_ids: Sequence[int]
    ) -> None:
        """Lock nhiều row contact (FOR UPDATE) 1 query — dùng trước khi
        cập nhật projection consent hàng loạt (import có bằng chứng)."""
        if not contact_ids:
            return
        await self.db.execute(
            select(SmsContact.id)
            .where(SmsContact.id.in_(set(contact_ids)))
            .with_for_update()
        )

    async def get_contact_by_phone(
        self, phone_normalized: str
    ) -> Optional[SmsContact]:
        res = await self.db.execute(
            select(SmsContact).where(
                SmsContact.phone_normalized == phone_normalized
            )
        )
        return res.scalars().first()

    async def get_contacts_by_phones(
        self, phones: Sequence[str]
    ) -> Dict[str, SmsContact]:
        """Map phone_normalized → contact cho 1 lô (anti-N+1 import)."""
        if not phones:
            return {}
        res = await self.db.execute(
            select(SmsContact).where(
                SmsContact.phone_normalized.in_(set(phones))
            )
        )
        return {c.phone_normalized: c for c in res.scalars().all()}

    async def list_contacts(
        self,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        consent_status: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> Tuple[int, List[SmsContact]]:
        base = select(SmsContact)
        conds = []
        if group_id is not None:
            base = base.join(
                SmsContactGroupMember,
                SmsContactGroupMember.contact_id == SmsContact.id,
            )
            conds.append(SmsContactGroupMember.group_id == group_id)
        if consent_status is not None:
            conds.append(
                SmsContact.marketing_consent_status == consent_status
            )
        if search:
            like = f"%{search.strip()}%"
            conds.append(
                or_(
                    SmsContact.full_name.ilike(like),
                    SmsContact.phone_normalized.ilike(like),
                    SmsContact.phone_international.ilike(like),
                )
            )
        if conds:
            base = base.where(*conds)
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsContact.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return int(total or 0), list(res.scalars().all())

    # ---------------------------------------------------------------
    # Membership
    # ---------------------------------------------------------------
    async def get_membership(
        self, group_id: int, contact_id: int
    ) -> Optional[SmsContactGroupMember]:
        res = await self.db.execute(
            select(SmsContactGroupMember).where(
                SmsContactGroupMember.group_id == group_id,
                SmsContactGroupMember.contact_id == contact_id,
            )
        )
        return res.scalars().first()

    async def get_existing_member_contact_ids(
        self, group_id: int, contact_ids: Sequence[int]
    ) -> Set[int]:
        """Tập contact_id ĐÃ là member nhóm (anti-N+1 import)."""
        if not contact_ids:
            return set()
        res = await self.db.execute(
            select(SmsContactGroupMember.contact_id).where(
                SmsContactGroupMember.group_id == group_id,
                SmsContactGroupMember.contact_id.in_(set(contact_ids)),
            )
        )
        return {row[0] for row in res.all()}

    async def create_membership(
        self, data: dict
    ) -> SmsContactGroupMember:
        member = SmsContactGroupMember(**data)
        self.db.add(member)
        await self.db.flush()
        return member

    async def delete_membership(
        self, member: SmsContactGroupMember
    ) -> None:
        await self.db.delete(member)
        await self.db.flush()

    # ---------------------------------------------------------------
    # Consent-event ledger
    # ---------------------------------------------------------------
    async def create_consent_event(
        self, data: dict
    ) -> SmsMarketingConsentEvent:
        event = SmsMarketingConsentEvent(**data)
        self.db.add(event)
        await self.db.flush()
        return event

    @staticmethod
    def _latest_event_order():
        """Thứ tự chọn event "mới nhất": occurred_at DESC; khi BẰNG nhau →
        REVOKE thắng (fail-closed, không để grant ghi-sau khôi phục revoke);
        cuối cùng id DESC cho ổn định."""
        revoke_first = case(
            (SmsMarketingConsentEvent.event_type == "revoked", 0), else_=1
        )
        return (
            SmsMarketingConsentEvent.occurred_at.desc(),
            revoke_first.asc(),
            SmsMarketingConsentEvent.id.desc(),
        )

    async def get_latest_consent_event(
        self, contact_id: int
    ) -> Optional[SmsMarketingConsentEvent]:
        """Event consent "mới nhất" của 1 contact (xem `_latest_event_order`)."""
        res = await self.db.execute(
            select(SmsMarketingConsentEvent)
            .where(SmsMarketingConsentEvent.contact_id == contact_id)
            .order_by(*self._latest_event_order())
            .limit(1)
        )
        return res.scalars().first()

    async def get_latest_consent_events_for_contacts(
        self, contact_ids: Sequence[int]
    ) -> Dict[int, SmsMarketingConsentEvent]:
        """Map contact_id → event "mới nhất" cho nhiều contact 1 query
        (DISTINCT ON) — thay N+1 khi reproject hàng loạt lúc import."""
        if not contact_ids:
            return {}
        res = await self.db.execute(
            select(SmsMarketingConsentEvent)
            .where(SmsMarketingConsentEvent.contact_id.in_(set(contact_ids)))
            .distinct(SmsMarketingConsentEvent.contact_id)
            .order_by(
                SmsMarketingConsentEvent.contact_id,
                *self._latest_event_order(),
            )
        )
        return {e.contact_id: e for e in res.scalars().all()}

    async def list_consent_events(
        self, contact_id: int, skip: int = 0, limit: int = 50
    ) -> Tuple[int, List[SmsMarketingConsentEvent]]:
        base = select(SmsMarketingConsentEvent).where(
            SmsMarketingConsentEvent.contact_id == contact_id
        )
        total = await self.db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        res = await self.db.execute(
            base.order_by(SmsMarketingConsentEvent.occurred_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return int(total or 0), list(res.scalars().all())

    # ---------------------------------------------------------------
    # Import batch
    # ---------------------------------------------------------------
    async def create_import_batch(
        self, data: dict
    ) -> SmsContactImportBatch:
        batch = SmsContactImportBatch(**data)
        self.db.add(batch)
        await self.db.flush()
        return batch
