# app/services/sms_resolve.py
"""
Resolver dùng chung cho bearer code `/r/{code}`, landing `/lp/{code}` và session
Phase 2 (§16.7 resolve mở rộng): tra `sms_campaign_recipient.token_hash` TRƯỚC,
không thấy → `sms_consult_link.token_hash`. Trả 1 kết quả chuẩn hoá để tracking/
landing/engagement service xử lý đồng nhất (contact_id thống nhất giữa 2 nguồn).

KHÔNG import fastapi; raise ResourceNotFoundError (404 generic). Không log raw
code.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from app.utils.tz import ensure_aware
from typing import Optional

from app.models.sms import SmsCampaign, SmsCampaignRecipient, SmsConsultLink
from app.repositories.sms_tracking_repository import SmsTrackingRepository
from app.utils.exceptions import ResourceNotFoundError
from app.utils.sms_token import compute_token_hash, is_valid_code

GENERIC_404 = "Liên kết không hợp lệ hoặc đã hết hạn"


_aware = ensure_aware  # alias tới helper tz chung (bỏ bản sao logic)


@dataclass
class ResolvedCode:
    """Nguồn 1 bearer code — campaign recipient HOẶC consult link."""

    kind: str  # "campaign" | "consult"
    contact_id: Optional[int]
    expires_at: Optional[datetime]
    # phone_normalized của nguồn (recipient snapshot / consult JOIN contact) —
    # tránh query get_contact_phone thêm ở opt-out/landing.
    phone_normalized: Optional[str] = None
    recipient: Optional[SmsCampaignRecipient] = None
    campaign: Optional[SmsCampaign] = None
    consult: Optional[SmsConsultLink] = None

    @property
    def is_expired(self) -> bool:
        return bool(
            self.expires_at
            and _aware(self.expires_at) <= datetime.now(timezone.utc)
        )


async def resolve_code(
    repo: SmsTrackingRepository, code: str, *, enforce_expiry: bool = True
) -> ResolvedCode:
    """Validate code → tra recipient TRƯỚC, không thấy → consult. Raise
    ResourceNotFoundError (404 generic) nếu sai/không thấy; nếu hết hạn và
    enforce_expiry → 404 (opt-out gọi với enforce_expiry=False, §NĐ91)."""
    if not is_valid_code(code):
        raise ResourceNotFoundError(detail=GENERIC_404)
    token_hash = compute_token_hash(code)

    found = await repo.lookup_by_token_hash(token_hash)
    if found is not None:
        recipient, campaign = found
        resolved = ResolvedCode(
            kind="campaign",
            contact_id=recipient.contact_id,
            expires_at=campaign.link_expires_at,
            phone_normalized=recipient.phone_normalized_snapshot,
            recipient=recipient,
            campaign=campaign,
        )
    else:
        found_consult = await repo.lookup_consult_by_token_hash(token_hash)
        if found_consult is None:
            raise ResourceNotFoundError(detail=GENERIC_404)
        consult, phone_normalized = found_consult
        resolved = ResolvedCode(
            kind="consult",
            contact_id=consult.contact_id,
            expires_at=consult.expires_at,
            phone_normalized=phone_normalized,
            consult=consult,
        )

    if enforce_expiry and resolved.is_expired:
        raise ResourceNotFoundError(detail=GENERIC_404)
    return resolved
