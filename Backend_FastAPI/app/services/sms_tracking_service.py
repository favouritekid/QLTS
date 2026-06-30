# app/services/sms_tracking_service.py
"""
Business logic resolve short-link `/r/{code}` (PR-5): validate code → tra
token_hash → kiểm hết hạn/invalidated → ghi click (bot eval + ip_hash) →
quyết định đích 302. Response 404 GENERIC cho mọi trường hợp không hợp lệ
(không lộ tồn tại code). KHÔNG log raw code.

KHÔNG import fastapi; raise domain exception; service flush (router commit).
Xem SMS_MARKETING_MODULE_DESIGN.md §6.
"""
import logging
from datetime import datetime, timezone
from typing import Mapping, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_bot import detect_bot
from app.utils.sms_token import compute_ip_hash, compute_token_hash, is_valid_code
from app.utils.sms_url import host_in_allowlist

log = logging.getLogger(__name__)

_GENERIC_404 = "Liên kết không hợp lệ hoặc đã hết hạn"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class SmsTrackingService:
    """Resolve /r/{code} → click + 302 target."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsTrackingRepository(db)

    async def resolve(
        self,
        code: str,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        """Trả URL đích cho 302. Raise ResourceNotFoundError (404 generic) nếu
        code sai/không thấy/hết hạn/external ngoài allowlist."""
        if not is_valid_code(code):
            raise ResourceNotFoundError(detail=_GENERIC_404)
        found = await self.repo.lookup_by_token_hash(compute_token_hash(code))
        if found is None:
            raise ResourceNotFoundError(detail=_GENERIC_404)
        recipient, campaign = found
        now = datetime.now(timezone.utc)
        if campaign.link_expires_at and _aware(campaign.link_expires_at) <= now:
            raise ResourceNotFoundError(detail=_GENERIC_404)

        # Đích redirect (re-check allowlist external — §6.2 lớp 2).
        if campaign.landing_type == "external":
            target = (campaign.landing_url or "").strip()
            if not target or not host_in_allowlist(target):
                log.warning(
                    "SMS /r: external landing_url ngoài allowlist campaign_id=%s",
                    campaign.id,
                )
                raise ResourceNotFoundError(detail=_GENERIC_404)
        else:
            # qlts_hosted → landing nội bộ (relative, cùng host public).
            target = f"/lp/{code}"

        # Ghi click (bot eval + ip_hash) — counter atomic ở repo.
        is_bot, reason = detect_bot(
            user_agent=user_agent,
            headers=headers,
            handed_off_at=recipient.handed_off_at,
            now=now,
        )
        await self.repo.record_click(
            recipient_id=recipient.id,
            ip_hash=compute_ip_hash(ip),
            user_agent=user_agent,
            is_bot=is_bot,
            bot_reason=reason,
            now=now,
        )
        await self.db.flush()
        return target
