# app/services/sms_consult_service.py
"""
Business logic P2-3 consult officer (§16.5/§16.7): officer tạo link tư vấn 1-1
cho 1 lead trong phạm vi IDOR của mình → match/tạo contact theo phone lead
(khóa thống nhất) → sinh consult link (short code raw TRẢ 1 LẦN). Và xem hồ sơ
'quan tâm ngành' của lead (qua contact match).

Consult 1-1 KHÔNG tự cấp consent marketing: contact tạo giữ
`marketing_consent_status='unknown'` (§16.5) → KHÔNG đủ điều kiện build campaign.

KHÔNG import fastapi; raise domain exception; service flush (router commit).
"""
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.sms_contact_repository import SmsContactRepository
from app.repositories.sms_engagement_repository import SmsEngagementRepository
from app.schemas import sms as sms_schemas
from app.utils.exceptions import ValidationError
from app.utils.phone_helpers import (
    is_vietnam_mobile,
    normalize_and_validate_vietnam_phone,
    to_zalo_phone,
)
from app.utils.sms_token import (
    build_link,
    compute_token_hash,
    ensure_token_secrets_configured,
    generate_short_code,
)


class SmsConsultService:
    """Officer consult link + lead interests (Phase 2 §16)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.contact_repo = SmsContactRepository(db)
        self.engagement_repo = SmsEngagementRepository(db)

    @staticmethod
    def _normalize_lead_phone(phone: Optional[str]) -> str:
        """(normalized) cho số di động lead — raise ValidationError nếu không
        phải di động VN hợp lệ (không tạo consult link cho số rác)."""
        normalized, valid = normalize_and_validate_vietnam_phone(phone)
        if not valid or not normalized or not is_vietnam_mobile(normalized):
            raise ValidationError(
                detail="Lead chưa có số di động hợp lệ để tạo link tư vấn."
            )
        return normalized

    async def create_consult_link(
        self, lead: models.Lead, current_user: models.User
    ) -> sms_schemas.SmsConsultLinkResponse:
        # Prod bắt buộc secret hash mạnh + base URL hợp lệ (link công khai).
        ensure_token_secrets_configured()
        normalized = self._normalize_lead_phone(lead.phone)

        # Match contact theo phone (khóa thống nhất); chưa có → tạo (consent
        # unknown — consult không tự cấp consent marketing §16.5).
        contact = await self.contact_repo.get_contact_by_phone(normalized)
        if contact is None:
            try:
                async with self.db.begin_nested():
                    contact = await self.contact_repo.create_contact(
                        {
                            "full_name": (lead.full_name or "Lead")[:255],
                            "phone_normalized": normalized,
                            "phone_international": to_zalo_phone(normalized),
                            "source_label": "lead_consult",
                            "created_by_id": getattr(current_user, "id", None),
                        }
                    )
            except IntegrityError:
                # Race: 2 request tạo cùng phone → lấy contact đã có.
                contact = await self.contact_repo.get_contact_by_phone(
                    normalized
                )
                if contact is None:
                    raise

        code = generate_short_code()
        consult = await self.engagement_repo.create_consult_link(
            {
                "lead_id": lead.id,
                "contact_id": contact.id,
                "created_by_id": getattr(current_user, "id", None),
                "token_hash": compute_token_hash(code),
                "landing_type": "qlts_hosted",
            }
        )
        return sms_schemas.SmsConsultLinkResponse(
            code=code,
            url=build_link(code),
            consult_link_id=consult.id,
            contact_id=contact.id,
        )

    async def lead_interests(
        self, lead: models.Lead
    ) -> sms_schemas.SmsLeadInterestResponse:
        """Interest của lead qua contact match phone. Rỗng nếu chưa có
        contact/tương tác. KHÔNG raise nếu phone lead không hợp lệ → trả rỗng."""
        normalized, valid = normalize_and_validate_vietnam_phone(lead.phone)
        if not valid or not normalized:
            return sms_schemas.SmsLeadInterestResponse(lead_id=lead.id)
        contact = await self.contact_repo.get_contact_by_phone(normalized)
        if contact is None:
            return sms_schemas.SmsLeadInterestResponse(lead_id=lead.id)
        rows = await self.engagement_repo.contact_interests(contact.id)
        return sms_schemas.SmsLeadInterestResponse(
            lead_id=lead.id,
            contact_id=contact.id,
            items=[
                sms_schemas.SmsContactInterestRow(
                    major_program_id=r.major_program_id,
                    program_name=name or "(ngành đã xoá)",
                    view_count=r.view_count,
                    total_dwell_seconds=r.total_dwell_seconds,
                    interest_score=r.interest_score,
                    first_interest_at=r.first_interest_at,
                    last_interest_at=r.last_interest_at,
                )
                for r, name in rows
            ],
        )
