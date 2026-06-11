# app/models/sms/__init__.py
"""SMS Marketing models (Phase 1 — 12 model). Xem SMS_MARKETING_MODULE_DESIGN.md §4."""
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
]
