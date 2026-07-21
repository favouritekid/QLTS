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
from app.services.sms_resolve import GENERIC_404, resolve_code
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_bot import detect_bot
from app.utils.sms_token import compute_ip_hash
from app.utils.sms_url import host_in_allowlist

log = logging.getLogger(__name__)


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
        code sai/không thấy/hết hạn/external ngoài allowlist. Resolve mở rộng:
        recipient TRƯỚC, không thấy → consult link (§16.7)."""
        resolved = await resolve_code(self.repo, code, enforce_expiry=True)
        now = datetime.now(timezone.utc)

        if resolved.kind == "campaign":
            campaign = resolved.campaign
            # Đích redirect (re-check allowlist external — §6.2 lớp 2).
            if campaign.landing_type == "external":
                target = (campaign.landing_url or "").strip()
                if not target or not host_in_allowlist(target):
                    log.warning(
                        "SMS /r: external landing_url ngoài allowlist "
                        "campaign_id=%s", campaign.id,
                    )
                    raise ResourceNotFoundError(detail=GENERIC_404)
            else:
                target = f"/lp/{code}"
            # mobile_channel=True: lượt này đến TỪ TIN SMS → chỉ mở được trên
            # điện thoại. UA desktop = máy quét chống spam của nhà mạng, vốn
            # lọt hết 3 dấu hiệu cũ và thổi phồng CTR (xem sms_bot).
            is_bot, reason = detect_bot(
                user_agent=user_agent,
                headers=headers,
                handed_off_at=resolved.recipient.handed_off_at,
                now=now,
                mobile_channel=True,
            )
            await self.repo.record_click(
                recipient_id=resolved.recipient.id,
                ip_hash=compute_ip_hash(ip),
                user_agent=user_agent,
                is_bot=is_bot,
                bot_reason=reason,
                now=now,
            )
        else:
            # Consult link — MVP luôn qlts_hosted danh mục nội bộ.
            target = f"/lp/{code}"
            is_bot, reason = detect_bot(
                user_agent=user_agent, headers=headers, now=now,
            )
            await self.repo.record_consult_click(
                consult_link_id=resolved.consult.id,
                ip_hash=compute_ip_hash(ip),
                user_agent=user_agent,
                is_bot=is_bot,
                bot_reason=reason,
                now=now,
            )
        await self.db.flush()
        return target
