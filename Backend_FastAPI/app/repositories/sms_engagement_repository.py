# app/repositories/sms_engagement_repository.py
"""
Data-access Phase 2 (§16) deep engagement — 3 bảng đo quan tâm ngành:
sms_landing_session, sms_program_view, sms_contact_program_interest + danh mục
ngành (major_program active) cho landing 2 tầng.

Chức năng: tạo/tra session (theo token_hash), mở program-view + sequence, cộng
dwell, aggregate interest (upsert atomic pg on_conflict), report 'ngành nóng'
(JOIN view↔session[+recipient] theo campaign/nhóm/thời gian, loại bot), và hồ
sơ sở thích 1 contact.

Standalone repository. Service flush, router commit. Xem SMS §16.
"""
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.major_program import MajorProgram
from app.models.sms import (
    SmsCampaignRecipient,
    SmsContactProgramInterest,
    SmsLandingSession,
    SmsProgramView,
)


class SmsEngagementRepository:
    """Repository session/view/interest Phase 2 + danh mục ngành."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------
    # Danh mục ngành (landing 2 tầng — tái dùng major_program active)
    # ---------------------------------------------------------------
    async def list_active_programs(self) -> List[MajorProgram]:
        res = await self.db.execute(
            select(MajorProgram)
            .where(MajorProgram.is_active.is_(True))
            .order_by(MajorProgram.degree_level, MajorProgram.name)
        )
        return list(res.scalars().all())

    async def get_active_program(
        self, major_program_id: int
    ) -> Optional[MajorProgram]:
        res = await self.db.execute(
            select(MajorProgram).where(
                MajorProgram.id == major_program_id,
                MajorProgram.is_active.is_(True),
            )
        )
        return res.scalars().first()

    # ---------------------------------------------------------------
    # Session
    # ---------------------------------------------------------------
    async def create_session(self, fields: dict) -> SmsLandingSession:
        row = SmsLandingSession(**fields)
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_session_by_token_hash(
        self, token_hash: str
    ) -> Optional[SmsLandingSession]:
        res = await self.db.execute(
            select(SmsLandingSession).where(
                SmsLandingSession.session_token_hash == token_hash
            )
        )
        return res.scalars().first()

    # ---------------------------------------------------------------
    # Program view
    # ---------------------------------------------------------------
    async def next_sequence_no(self, session_id: int) -> int:
        cur = await self.db.scalar(
            select(func.coalesce(func.max(SmsProgramView.sequence_no), 0)).where(
                SmsProgramView.session_id == session_id
            )
        )
        return int(cur or 0) + 1

    async def create_program_view(self, fields: dict) -> SmsProgramView:
        row = SmsProgramView(**fields)
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_program_view(
        self, view_id: int, session_id: int
    ) -> Optional[SmsProgramView]:
        """Lấy view PHẢI thuộc session (chống dùng token phiên khác đẩy dwell
        vào view lạ)."""
        res = await self.db.execute(
            select(SmsProgramView).where(
                SmsProgramView.id == view_id,
                SmsProgramView.session_id == session_id,
            )
        )
        return res.scalars().first()

    async def views_for_interest(
        self, contact_id: int, major_program_id: int
    ) -> List[Tuple[int, datetime]]:
        """(dwell_seconds, viewed_at) MỌI view của cặp (contact, ngành) — để
        tính lại interest_score (Σ dwell_factor×recency)."""
        res = await self.db.execute(
            select(SmsProgramView.dwell_seconds, SmsProgramView.viewed_at).where(
                SmsProgramView.contact_id == contact_id,
                SmsProgramView.major_program_id == major_program_id,
            )
        )
        return [(int(d), v) for d, v in res.all()]

    # ---------------------------------------------------------------
    # Aggregate interest (upsert atomic)
    # ---------------------------------------------------------------
    async def upsert_interest(
        self,
        *,
        contact_id: int,
        major_program_id: int,
        view_count: int,
        total_dwell_seconds: int,
        first_interest_at: Optional[datetime],
        last_interest_at: Optional[datetime],
        interest_score: float,
        now: datetime,
    ) -> None:
        """INSERT ... ON CONFLICT(contact,program) DO UPDATE — atomic, last
        writer wins. Giá trị tính lại từ view (nguồn sự thật) nên tự lành khi
        2 heartbeat đua. first_interest giữ min (không lùi khi update)."""
        stmt = (
            pg_insert(SmsContactProgramInterest)
            .values(
                contact_id=contact_id,
                major_program_id=major_program_id,
                view_count=view_count,
                total_dwell_seconds=total_dwell_seconds,
                first_interest_at=first_interest_at,
                last_interest_at=last_interest_at,
                interest_score=interest_score,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["contact_id", "major_program_id"],
                set_={
                    "view_count": view_count,
                    "total_dwell_seconds": total_dwell_seconds,
                    "first_interest_at": func.least(
                        SmsContactProgramInterest.first_interest_at,
                        first_interest_at,
                    ),
                    "last_interest_at": last_interest_at,
                    "interest_score": interest_score,
                    "updated_at": now,
                },
            )
        )
        await self.db.execute(stmt)

    # ---------------------------------------------------------------
    # Report 'ngành nóng' (§16.7) — JOIN view↔session[+recipient]
    # ---------------------------------------------------------------
    def _report_conds(
        self,
        *,
        campaign_id: Optional[int],
        group_id: Optional[int],
        major_program_id: Optional[int],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
    ):
        # Loại session bot khỏi số liệu 'quan tâm' (chỉ đo người thật chạy JS).
        conds = [SmsLandingSession.is_suspected_bot.is_(False)]
        if campaign_id is not None:
            conds.append(SmsLandingSession.campaign_id == campaign_id)
        if major_program_id is not None:
            conds.append(SmsProgramView.major_program_id == major_program_id)
        if date_from is not None:
            conds.append(SmsProgramView.viewed_at >= date_from)
        if date_to is not None:
            conds.append(SmsProgramView.viewed_at <= date_to)
        return conds

    def _report_from(self, *, group_id: Optional[int]):
        """FROM view JOIN session; JOIN recipient khi lọc theo nhóm (group_ids
        snapshot ở recipient, không ở session)."""
        j = SmsProgramView.__table__.join(
            SmsLandingSession.__table__,
            SmsLandingSession.id == SmsProgramView.session_id,
        )
        if group_id is not None:
            j = j.join(
                SmsCampaignRecipient.__table__,
                SmsCampaignRecipient.id == SmsLandingSession.recipient_id,
            )
        return j

    async def program_interest_report(
        self,
        *,
        campaign_id: Optional[int] = None,
        group_id: Optional[int] = None,
        major_program_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Tuple[Optional[int], str, int, int, int]]:
        """(major_program_id, program_name, distinct_contacts, view_count,
        total_dwell) theo ngành, rank total_dwell desc. Ngành bị xoá →
        major_program_id NULL, name = snapshot gần nhất."""
        conds = self._report_conds(
            campaign_id=campaign_id,
            group_id=group_id,
            major_program_id=major_program_id,
            date_from=date_from,
            date_to=date_to,
        )
        if group_id is not None:
            conds.append(
                SmsCampaignRecipient.group_ids_snapshot.contains([group_id])
            )
        total_dwell = func.coalesce(func.sum(SmsProgramView.dwell_seconds), 0)
        res = await self.db.execute(
            select(
                SmsProgramView.major_program_id.label("program_id"),
                func.max(SmsProgramView.program_name_snapshot).label("name"),
                func.count(func.distinct(SmsProgramView.contact_id)).label(
                    "distinct_contacts"
                ),
                func.count().label("view_count"),
                total_dwell.label("total_dwell"),
            )
            .select_from(self._report_from(group_id=group_id))
            .where(and_(*conds))
            .group_by(SmsProgramView.major_program_id)
            .order_by(total_dwell.desc())
            .limit(limit)
        )
        return [
            (r.program_id, r.name, int(r.distinct_contacts), int(r.view_count),
             int(r.total_dwell))
            for r in res.all()
        ]

    async def program_interest_totals(
        self,
        *,
        campaign_id: Optional[int] = None,
        group_id: Optional[int] = None,
        major_program_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Tuple[int, int, int]:
        """(distinct_contacts_total, view_count_total, total_dwell) toàn dải —
        distinct contact tính riêng (không sum row-level distinct)."""
        conds = self._report_conds(
            campaign_id=campaign_id,
            group_id=group_id,
            major_program_id=major_program_id,
            date_from=date_from,
            date_to=date_to,
        )
        if group_id is not None:
            conds.append(
                SmsCampaignRecipient.group_ids_snapshot.contains([group_id])
            )
        res = await self.db.execute(
            select(
                func.count(func.distinct(SmsProgramView.contact_id)),
                func.count(),
                func.coalesce(func.sum(SmsProgramView.dwell_seconds), 0),
            )
            .select_from(self._report_from(group_id=group_id))
            .where(and_(*conds))
        )
        r = res.first()
        return int(r[0]), int(r[1]), int(r[2])

    # ---------------------------------------------------------------
    # Hồ sơ sở thích 1 contact
    # ---------------------------------------------------------------
    async def contact_interests(
        self, contact_id: int
    ) -> List[Tuple[SmsContactProgramInterest, str]]:
        """(interest_row, program_name) của contact, rank total_dwell desc.
        JOIN major_program lấy tên (FK CASCADE → ngành xoá thì row cũng xoá)."""
        res = await self.db.execute(
            select(SmsContactProgramInterest, MajorProgram.name)
            .join(
                MajorProgram,
                MajorProgram.id == SmsContactProgramInterest.major_program_id,
            )
            .where(SmsContactProgramInterest.contact_id == contact_id)
            .order_by(SmsContactProgramInterest.total_dwell_seconds.desc())
        )
        return [(row[0], row[1]) for row in res.all()]
