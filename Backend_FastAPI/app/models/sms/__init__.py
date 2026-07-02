# app/models/sms/__init__.py
"""SMS Marketing models (Phase 1 — 12 model + Phase 2 §16 — 3 model deep engagement).
Xem SMS_MARKETING_MODULE_DESIGN.md §4 + §16."""
from .contact_group import SmsContactGroup
from .contact import SmsContact
from .contact_group_member import SmsContactGroupMember
from .contact_import_batch import SmsContactImportBatch
from .prefix_carrier_rule import SmsPrefixCarrierRule
from .campaign import SmsCampaign
from .campaign_group import SmsCampaignGroup
from .campaign_recipient import SmsCampaignRecipient
from .campaign_export_batch import SmsCampaignExportBatch
from .click_event import SmsClickEvent
from .opt_out import SmsOptOut
from .marketing_consent_event import SmsMarketingConsentEvent
# Phase 2 (§16) — deep engagement / đo quan tâm ngành
from .landing_session import SmsLandingSession
from .program_view import SmsProgramView
from .contact_program_interest import SmsContactProgramInterest

__all__ = [
    "SmsContactGroup",
    "SmsContact",
    "SmsContactGroupMember",
    "SmsContactImportBatch",
    "SmsPrefixCarrierRule",
    "SmsCampaign",
    "SmsCampaignGroup",
    "SmsCampaignRecipient",
    "SmsCampaignExportBatch",
    "SmsClickEvent",
    "SmsOptOut",
    "SmsMarketingConsentEvent",
    # Phase 2
    "SmsLandingSession",
    "SmsProgramView",
    "SmsContactProgramInterest",
]
