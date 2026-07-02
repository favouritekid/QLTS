# app/services/sms_engagement_service.py
"""
Business logic Phase 2 (§16) deep engagement — đo "ngành thực sự quan tâm":
- start_session: resolve `/lp/{code}` (campaign recipient) → tạo phiên, sinh
  session_token raw TRẢ 1 LẦN (lưu hash), gắn contact_id (khóa thống nhất).
- record_program_view: mở 1 lượt xem trang ngành (snapshot tên ngành).
- heartbeat: cộng dwell trang ngành (clamp wall-clock chống thổi phồng) →
  cập nhật aggregate interest_score (§18.F) cho cặp (contact, ngành).

KHÔNG import fastapi; raise domain exception; service flush (router commit).
Bot (UA/prefetch) vẫn tạo phiên (không lộ việc phát hiện) NHƯNG bị loại khỏi
interest + report. Xem SMS_MARKETING_MODULE_DESIGN.md §16.
"""
import logging
from datetime import datetime, timezone
from typing import Mapping, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.sms_engagement_repository import SmsEngagementRepository
from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.schemas import sms as sms_schemas
from app.services.sms_resolve import resolve_code
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_bot import detect_bot
from app.utils.sms_interest import compute_interest_score
from app.utils.sms_token import (
    compute_ip_hash,
    compute_session_token_hash,
    generate_session_token,
    is_valid_code,
)

log = logging.getLogger(__name__)

_GENERIC_404 = "Liên kết không hợp lệ hoặc đã hết hạn"
# Dung sai clamp dwell: cho phép dwell client báo vượt thời gian thực đã trôi
# tối đa ngần này (bù lệch đồng hồ + độ trễ heartbeat cuối). Chống client gửi
# dwell_seconds khổng lồ (thổi phồng interest).
_HEARTBEAT_GRACE_SECONDS = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class SmsEngagementService:
    """Session + program-view + heartbeat + aggregate interest (Phase 2)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsEngagementRepository(db)
        self.tracking_repo = SmsTrackingRepository(db)

    async def _resolve_session(self, session_token: str):
        """Session theo token hash (bearer). None → 404 generic.

        BEARER SỐNG-HẾT-PHIÊN (có chủ đích, /review #3): expiry của campaign
        link CHỈ gate lúc TẠO phiên (start_session→_resolve_recipient), /r/ và
        landing GET. Program-view/heartbeat KHÔNG re-check expiry: người dùng
        thật vào bằng link còn hạn rồi ĐANG đọc, nếu link hết hạn giữa chừng mà
        cắt đo dwell = làm HỎNG số liệu của chính người thật đó. Token 256-bit
        bất khả đoán + rate-limit theo IP + interest_score có trần → không cần
        chặn theo expiry ở đây. `code` path chỉ validate format (routing)."""
        token = (session_token or "").strip()
        if not token:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        session = await self.repo.get_session_by_token_hash(
            compute_session_token_hash(token)
        )
        if session is None:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        return session

    # ---------------------------------------------------------------
    # Start session (POST /landing/{code}/session)
    # ---------------------------------------------------------------
    async def start_session(
        self,
        code: str,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        headers: Optional[Mapping[str, str]] = None,
    ) -> sms_schemas.SmsSessionStartResponse:
        # Resolve mở rộng: recipient (campaign) HOẶC consult link (§16.7).
        resolved = await resolve_code(
            self.tracking_repo, code, enforce_expiry=True
        )
        # contact_id = khóa thống nhất gắn interest; NULL (recipient mất contact
        # do xoá) → không quy được sở thích → 404 (ca hiếm; consult luôn có).
        if resolved.contact_id is None:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        now = datetime.now(timezone.utc)
        is_bot, _reason = detect_bot(
            user_agent=user_agent, headers=headers, now=now
        )
        raw_token = generate_session_token()
        session = await self.repo.create_session(
            {
                "contact_id": resolved.contact_id,
                "source_type": resolved.kind,  # "campaign" | "consult"
                "recipient_id": (
                    resolved.recipient.id
                    if resolved.kind == "campaign" else None
                ),
                "campaign_id": (
                    resolved.campaign.id
                    if resolved.kind == "campaign" else None
                ),
                "consult_link_id": (
                    resolved.consult.id
                    if resolved.kind == "consult" else None
                ),
                "session_token_hash": compute_session_token_hash(raw_token),
                "started_at": now,
                "last_heartbeat_at": now,
                "ip_hash": compute_ip_hash(ip),
                "user_agent": (user_agent[:512] if user_agent else None),
                "is_suspected_bot": is_bot,
            }
        )
        return sms_schemas.SmsSessionStartResponse(
            session_token=raw_token, session_id=session.id
        )

    # ---------------------------------------------------------------
    # Program view (POST /landing/{code}/program-view)
    # ---------------------------------------------------------------
    async def record_program_view(
        self, code: str, payload: sms_schemas.SmsProgramViewRequest
    ) -> sms_schemas.SmsProgramViewResponse:
        if not is_valid_code(code):
            raise ResourceNotFoundError(detail=_GENERIC_404)
        session = await self._resolve_session(payload.session_token)
        program = await self.repo.get_active_program(payload.major_program_id)
        if program is None:
            # Ngành không tồn tại/không active → không đo (404 generic).
            raise ResourceNotFoundError(detail=_GENERIC_404)
        seq = await self.repo.next_sequence_no(session.id)
        view = await self.repo.create_program_view(
            {
                "session_id": session.id,
                "contact_id": session.contact_id,
                "major_program_id": program.id,
                "program_offering_id": payload.program_offering_id,
                "program_name_snapshot": program.name[:255],
                "viewed_at": datetime.now(timezone.utc),
                "dwell_seconds": 0,
                "sequence_no": seq,
            }
        )
        return sms_schemas.SmsProgramViewResponse(
            program_view_id=view.id, sequence_no=seq
        )

    # ---------------------------------------------------------------
    # Heartbeat (POST /landing/{code}/heartbeat)
    # ---------------------------------------------------------------
    async def heartbeat(
        self, code: str, payload: sms_schemas.SmsHeartbeatRequest
    ) -> sms_schemas.SmsHeartbeatResponse:
        if not is_valid_code(code):
            raise ResourceNotFoundError(detail=_GENERIC_404)
        session = await self._resolve_session(payload.session_token)
        view = await self.repo.get_program_view(
            payload.program_view_id, session.id
        )
        if view is None:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        now = datetime.now(timezone.utc)
        # Clamp: dwell ≤ thời gian thực đã trôi kể từ khi mở view + grace, và
        # đơn điệu tăng (heartbeat trễ/trùng không làm tụt). Chống thổi phồng.
        elapsed = int((now - _aware(view.viewed_at)).total_seconds())
        wall_cap = max(elapsed, 0) + _HEARTBEAT_GRACE_SECONDS
        new_dwell = max(view.dwell_seconds, min(payload.dwell_seconds, wall_cap))
        view.dwell_seconds = new_dwell
        session.last_heartbeat_at = now
        await self.db.flush()
        # active_seconds = Σ dwell mọi view của phiên (DERIVE sau flush, nguồn
        # sự thật) → chống lost-update khi 2 tab heartbeat // (không cộng delta).
        active_seconds = await self.repo.session_total_dwell(session.id)
        session.active_seconds = active_seconds
        # Cập nhật aggregate interest — chỉ session người thật + ngành còn sống.
        if not session.is_suspected_bot and view.major_program_id is not None:
            await self._recompute_interest(
                contact_id=session.contact_id,
                major_program_id=view.major_program_id,
                now=now,
            )
        await self.db.flush()
        return sms_schemas.SmsHeartbeatResponse(
            ok=True,
            dwell_seconds=new_dwell,
            active_seconds=active_seconds,
        )

    async def _recompute_interest(
        self, *, contact_id: int, major_program_id: int, now: datetime
    ) -> None:
        """Tính lại interest_score từ MỌI view của (contact, ngành) — nguồn sự
        thật là program_view (tự lành khi 2 heartbeat đua)."""
        views = await self.repo.views_for_interest(contact_id, major_program_id)
        if not views:
            return
        # Build 1 lần (normalize tz), rồi derive total_dwell/first/last từ đó.
        aware_views = [(d, _aware(v)) for d, v in views]
        viewed_ats = [v for _, v in aware_views]
        score = compute_interest_score(
            aware_views,
            now,
            dwell_cap=settings.SMS_INTEREST_DWELL_CAP,
            half_life_days=settings.SMS_INTEREST_HALF_LIFE,
            k=settings.SMS_INTEREST_K,
        )
        await self.repo.upsert_interest(
            contact_id=contact_id,
            major_program_id=major_program_id,
            view_count=len(aware_views),
            total_dwell_seconds=sum(d for d, _ in aware_views),
            first_interest_at=min(viewed_ats),
            last_interest_at=max(viewed_ats),
            interest_score=score,
            now=now,
        )
