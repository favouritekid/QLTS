"""
Seed a reusable notification template library from the event catalog.

Design:
- Seeds one baseline internal template for every active `notification_class="user"` event.
- Seeds a small ZNS draft pack for external-ready events.
- Templates are inert by default because `notification_template` has no enabled flag.
  They only affect runtime once referenced by a rule/action.

Usage:
    python -m app.scripts.seed_notification_template_library --dry-run
    python -m app.scripts.seed_notification_template_library --apply
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable

from app import models
from app.core.event_catalog import get_notifiable_events
from app.database import AsyncSessionLocal


@dataclass(frozen=True)
class TemplateSeed:
    name: str
    template_code: str
    description: str
    title_template: str
    message_template: str
    link_template: str | None
    variables: list[str]
    category: str
    supported_channels: list[str]
    allowed_events: list[str]
    template_type: str
    is_system: bool = False


_INTERNAL_OVERRIDES: dict[str, dict[str, str | list[str]]] = {
    "lead_assigned": {
        "title_template": "Lead Ä‘Æ°á»£c phÃ¢n cÃ´ng: $lead_name",
        "message_template": "Lead $lead_name Ä‘Ã£ Ä‘Æ°á»£c phÃ¢n cÃ´ng cho báº¡n. SÄT: $lead_phone.",
    },
    "lead_assignment_failed": {
        "title_template": "PhÃ¢n cÃ´ng lead tháº¥t báº¡i",
        "message_template": "Lead $lead_name chÆ°a thá»ƒ phÃ¢n cÃ´ng tá»± Ä‘á»™ng. LÃ½ do: $reason.",
    },
    "lead_reassigned": {
        "title_template": "Lead Ä‘Æ°á»£c chuyá»ƒn giao",
        "message_template": "Lead #$lead_id Ä‘Ã£ Ä‘Æ°á»£c chuyá»ƒn giao. LÃ½ do: $reason.",
    },
    "lead_status_changed": {
        "title_template": "Lead Ä‘á»•i tráº¡ng thÃ¡i: $lead_name",
        "message_template": "Lead $lead_name Ä‘Ã£ chuyá»ƒn tá»« '$old_status' sang '$new_status'.",
    },
    "lead_created": {
        "title_template": "Lead má»›i: $lead_name",
        "message_template": "Há»‡ thá»‘ng vá»«a táº¡o lead má»›i $lead_name tá»« nguá»“n $source.",
    },
    "lead_deleted": {
        "title_template": "Lead bá»‹ xÃ³a",
        "message_template": "Lead $lead_name Ä‘Ã£ bá»‹ xÃ³a khá»i há»‡ thá»‘ng.",
    },
    "lead_restored": {
        "title_template": "Lead Ä‘Æ°á»£c khÃ´i phá»¥c",
        "message_template": "Lead $lead_name Ä‘Ã£ Ä‘Æ°á»£c khÃ´i phá»¥c láº¡i.",
    },
    "lead_imported": {
        "title_template": "Import lead hoÃ n táº¥t",
        "message_template": "ÄÃ£ import $total_imported lead tá»« file $filename.",
    },
    "officer_availability_changed": {
        "title_template": "Officer Ä‘á»•i tráº¡ng thÃ¡i sáºµn sÃ ng",
        "message_template": "Officer $username Ä‘Ã£ Ä‘á»•i tráº¡ng thÃ¡i tá»« '$old_status' sang '$new_status'.",
    },
    "consultation_created": {
        "title_template": "TÆ° váº¥n má»›i cho lead #$lead_id",
        "message_template": "ÄÃ£ táº¡o lá»‹ch sá»­ tÆ° váº¥n má»›i cho lead #$lead_id vá»›i tráº¡ng thÃ¡i $status_id.",
    },
    "consultation_updated": {
        "title_template": "Cáº­p nháº­t tÆ° váº¥n cho lead #$lead_id",
        "message_template": "TÆ° váº¥n #$consultation_id Ä‘Ã£ Ä‘á»•i tráº¡ng thÃ¡i tá»« '$old_status_id' sang '$new_status_id'.",
    },
    "consultation_deleted": {
        "title_template": "XÃ³a báº£n ghi tÆ° váº¥n",
        "message_template": "Báº£n ghi tÆ° váº¥n #$consultation_id cá»§a lead #$lead_id Ä‘Ã£ bá»‹ xÃ³a.",
    },
    "consultation_reminder": {
        "title_template": "Nháº¯c lá»‹ch tÆ° váº¥n: $lead_name",
        "message_template": "Báº¡n cÃ³ lá»‹ch tÆ° váº¥n vá»›i $lead_name sau $minutes_until phÃºt.",
    },
    "application_created": {
        "title_template": "Há»“ sÆ¡ má»›i Ä‘Æ°á»£c táº¡o",
        "message_template": "Há»“ sÆ¡ #$application_id vá»«a Ä‘Æ°á»£c táº¡o cho lead #$lead_id.",
    },
    "application_status_changed": {
        "title_template": "Há»“ sÆ¡ Ä‘á»•i tráº¡ng thÃ¡i",
        "message_template": "Há»“ sÆ¡ #$application_id Ä‘Ã£ chuyá»ƒn tá»« '$old_status' sang '$new_status'.",
    },
    "application_deleted": {
        "title_template": "Há»“ sÆ¡ bá»‹ xÃ³a",
        "message_template": "Há»“ sÆ¡ #$application_id cá»§a lead $lead_name Ä‘Ã£ bá»‹ xÃ³a.",
    },
    "payment_received": {
        "title_template": "ÄÃ£ ghi nháº­n thanh toÃ¡n",
        "message_template": "Há»‡ thá»‘ng Ä‘Ã£ ghi nháº­n thanh toÃ¡n #$payment_id vá»›i sá»‘ tiá»n $amount.",
    },
    "payment_verified": {
        "title_template": "Thanh toÃ¡n Ä‘Æ°á»£c xÃ¡c nháº­n",
        "message_template": "Thanh toÃ¡n #$payment_id Ä‘Ã£ Ä‘Æ°á»£c xÃ¡c nháº­n vá»›i sá»‘ tiá»n $amount.",
    },
    "ctv_claim_submitted": {
        "title_template": "CTV gá»­i claim má»›i",
        "message_template": "CTV $collaborator_name vá»«a gá»­i claim cho lead $lead_name.",
    },
    "ctv_claim_approved": {
        "title_template": "Claim Ä‘Æ°á»£c duyá»‡t",
        "message_template": "Claim #$claim_id cho lead $lead_name Ä‘Ã£ Ä‘Æ°á»£c duyá»‡t.",
    },
    "ctv_claim_rejected": {
        "title_template": "Claim bá»‹ tá»« chá»‘i",
        "message_template": "Claim #$claim_id cho lead $lead_name bá»‹ tá»« chá»‘i. LÃ½ do: $rejection_reason.",
    },
    "ctv_approved": {
        "title_template": "TÃ i khoáº£n CTV Ä‘Æ°á»£c duyá»‡t",
        "message_template": "TÃ i khoáº£n cá»™ng tÃ¡c viÃªn $collaborator_name Ä‘Ã£ Ä‘Æ°á»£c duyá»‡t.",
    },
    "ctv_suspended": {
        "title_template": "TÃ i khoáº£n CTV bá»‹ Ä‘Ã¬nh chá»‰",
        "message_template": "TÃ i khoáº£n cá»™ng tÃ¡c viÃªn $collaborator_name Ä‘Ã£ bá»‹ Ä‘Ã¬nh chá»‰. LÃ½ do: $reason.",
    },
    "ctv_commission_created": {
        "title_template": "PhÃ¡t sinh hoa há»“ng má»›i",
        "message_template": "Báº¡n cÃ³ khoáº£n hoa há»“ng má»›i #$commission_id vá»›i sá»‘ tiá»n $amount.",
    },
    "ctv_attribution_expiring": {
        "title_template": "Quyá»n giá»›i thiá»‡u sáº¯p háº¿t háº¡n",
        "message_template": "Quyá»n giá»›i thiá»‡u lead #$lead_id sáº½ háº¿t háº¡n sau $days_remaining ngÃ y.",
    },
    "ctv_attribution_expired": {
        "title_template": "Quyá»n giá»›i thiá»‡u Ä‘Ã£ háº¿t háº¡n",
        "message_template": "Quyá»n giá»›i thiá»‡u cho lead #$lead_id Ä‘Ã£ háº¿t háº¡n.",
    },
    "ctv_weekly_summary": {
        "title_template": "BÃ¡o cÃ¡o tuáº§n cá»™ng tÃ¡c viÃªn",
        "message_template": "Tuáº§n $week: $new_leads lead má»›i, $commissions hoa há»“ng, tá»•ng thu nháº­p $total_earnings.",
    },
    "system_alert": {
        "title_template": "Cáº£nh bÃ¡o há»‡ thá»‘ng: $severity",
        "message_template": "$message",
    },
    "holiday_calendar_incomplete": {
        "title_template": "Lá»‹ch nghá»‰ lá»… chÆ°a Ä‘áº§y Ä‘á»§",
        "message_template": "$message (nÄƒm $year).",
    },
    "system_announcement": {
        "title_template": "$title",
        "message_template": "$message",
    },
    "user_role_changed": {
        "title_template": "Vai trÃ² tÃ i khoáº£n thay Ä‘á»•i",
        "message_template": "TÃ i khoáº£n cá»§a báº¡n Ä‘Ã£ Ä‘á»•i tá»« '$old_role' sang '$new_role'.",
    },
    "user_deactivated": {
        "title_template": "TÃ i khoáº£n bá»‹ vÃ´ hiá»‡u hÃ³a",
        "message_template": "TÃ i khoáº£n $username Ä‘Ã£ bá»‹ vÃ´ hiá»‡u hÃ³a. LÃ½ do: $reason.",
    },
    "pipeline_config_updated": {
        "title_template": "Cáº­p nháº­t cáº¥u hÃ¬nh pipeline",
        "message_template": "Cáº¥u hÃ¬nh $config_type Ä‘Ã£ Ä‘Æ°á»£c $operation trÃªn tÃ i nguyÃªn $resource_id.",
    },
    "suspicious_login": {
        "title_template": "ÄÄƒng nháº­p Ä‘Ã¡ng ngá»",
        "message_template": "PhÃ¡t hiá»‡n Ä‘Äƒng nháº­p Ä‘Ã¡ng ngá» tá»« IP $ip_address táº¡i $location.",
    },
}


_ZNS_DRAFTS: list[TemplateSeed] = [
    TemplateSeed(
        name="ZNS Draft - Payment Verified v1",
        template_code="ZNS_PAYMENT_VERIFIED_V1",
        description="Draft mapping for external applicant notification when payment is verified.",
        title_template="Thanh toÃ¡n Ä‘Æ°á»£c xÃ¡c nháº­n",
        message_template="Thanh toÃ¡n #$payment_id Ä‘Ã£ Ä‘Æ°á»£c xÃ¡c nháº­n vá»›i sá»‘ tiá»n $amount.",
        link_template=None,
        variables=["payment_id", "invoice_id", "fee_id", "amount", "verified_at", "lead_id"],
        category="finance",
        supported_channels=["zalo"],
        allowed_events=["payment_verified"],
        template_type="zalo_zns",
    ),
    TemplateSeed(
        name="ZNS Draft - Application Status Changed v1",
        template_code="ZNS_APPLICATION_STATUS_CHANGED_V1",
        description="Draft mapping for applicant-facing application status updates.",
        title_template="Há»“ sÆ¡ thay Ä‘á»•i tráº¡ng thÃ¡i",
        message_template="Há»“ sÆ¡ #$application_id Ä‘Ã£ chuyá»ƒn sang tráº¡ng thÃ¡i '$new_status'.",
        link_template=None,
        variables=["application_id", "lead_id", "old_status", "new_status"],
        category="application",
        supported_channels=["zalo"],
        allowed_events=["application_status_changed"],
        template_type="zalo_zns",
    ),
    TemplateSeed(
        name="ZNS Draft - Consultation Reminder v1",
        template_code="ZNS_CONSULTATION_REMINDER_V1",
        description="Draft mapping for reminder before consultation.",
        title_template="Nháº¯c lá»‹ch tÆ° váº¥n",
        message_template="Báº¡n cÃ³ lá»‹ch tÆ° váº¥n vá»›i $lead_name sau $minutes_until phÃºt.",
        link_template=None,
        variables=["consultation_id", "lead_id", "lead_name", "lead_phone", "scheduled_at", "minutes_until"],
        category="consultation",
        supported_channels=["zalo"],
        allowed_events=["consultation_reminder"],
        template_type="zalo_zns",
    )
]


def _default_internal_templates() -> list[TemplateSeed]:
    templates: list[TemplateSeed] = []
    for definition in get_notifiable_events():
        event_key = definition.event.value
        overrides = _INTERNAL_OVERRIDES.get(event_key, {})
        templates.append(
            TemplateSeed(
                name=f"{definition.display_name} (v1)",
                template_code=f"TPL_{event_key.upper()}_V1",
                description=f"Baseline reusable template for event '{event_key}'.",
                title_template=str(overrides.get("title_template", definition.display_name)),
                message_template=str(
                    overrides.get(
                        "message_template",
                        definition.description or definition.display_name,
                    )
                ),
                link_template=None,
                variables=[v.name for v in definition.variables],
                category=definition.category,
                supported_channels=list(definition.default_channels),
                allowed_events=[event_key],
                template_type="system",
            )
        )
    return templates


def _all_templates() -> list[TemplateSeed]:
    return _default_internal_templates() + _ZNS_DRAFTS


async def _upsert_template(session, seed: TemplateSeed) -> str:
    from sqlalchemy import select

    result = await session.execute(
        select(models.NotificationTemplate).where(
            models.NotificationTemplate.template_code == seed.template_code
        )
    )
    existing = result.scalar_one_or_none()

    payload = {
        "name": seed.name,
        "template_code": seed.template_code,
        "description": seed.description,
        "title_template": seed.title_template,
        "message_template": seed.message_template,
        "link_template": seed.link_template,
        "variables": seed.variables,
        "category": seed.category,
        "supported_channels": seed.supported_channels,
        "allowed_events": seed.allowed_events,
        "template_type": seed.template_type,
        "is_system": seed.is_system,
    }

    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return "updated"

    session.add(models.NotificationTemplate(**payload, usage_count=0, created_by=None))
    return "created"


def _summarize(seeds: Iterable[TemplateSeed]) -> tuple[int, int]:
    internal_count = 0
    zns_count = 0
    for seed in seeds:
        if seed.template_type == "zalo_zns":
            zns_count += 1
        else:
            internal_count += 1
    return internal_count, zns_count


async def main(apply_changes: bool) -> None:
    seeds = _all_templates()
    internal_count, zns_count = _summarize(seeds)

    print(f"Prepared {len(seeds)} templates total")
    print(f"  - internal/system: {internal_count}")
    print(f"  - zalo_zns drafts: {zns_count}")

    if not apply_changes:
        print("Dry run only. Pass --apply to write to database.")
        for seed in seeds:
            print(f"[DRY-RUN] {seed.template_code} | {seed.template_type} | {seed.allowed_events[0]}")
        return

    async with AsyncSessionLocal() as session:
        created = 0
        updated = 0
        for seed in seeds:
            action = await _upsert_template(session, seed)
            if action == "created":
                created += 1
            else:
                updated += 1
        await session.commit()

    print(f"Template library sync complete: created={created}, updated={updated}")
    print("Note: templates are inert until attached to a rule/action.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist templates to the database")
    parser.add_argument("--dry-run", action="store_true", help="Preview templates without writing (default)")
    args = parser.parse_args()

    apply_changes = args.apply
    if not args.apply and not args.dry_run:
        apply_changes = False

    import asyncio
    asyncio.run(main(apply_changes=apply_changes))

