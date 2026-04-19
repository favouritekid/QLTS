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
        "title_template": "Lead \u0111\u01b0\u1ee3c ph\u00e2n c\u00f4ng: $lead_name",
        "message_template": "Lead $lead_name \u0111\u00e3 \u0111\u01b0\u1ee3c ph\u00e2n c\u00f4ng cho b\u1ea1n. S\u0110T: $lead_phone.",
    },
    "lead_assignment_failed": {
        "title_template": "Ph\u00e2n c\u00f4ng lead th\u1ea5t b\u1ea1i",
        "message_template": "Lead $lead_name ch\u01b0a th\u1ec3 ph\u00e2n c\u00f4ng t\u1ef1 \u0111\u1ed9ng. L\u00fd do: $reason.",
    },
    "lead_reassigned": {
        "title_template": "Lead \u0111\u01b0\u1ee3c chuy\u1ec3n giao",
        "message_template": "Lead #$lead_id \u0111\u00e3 \u0111\u01b0\u1ee3c chuy\u1ec3n giao. L\u00fd do: $reason.",
    },
    "lead_status_changed": {
        "title_template": "Lead \u0111\u1ed5i tr\u1ea1ng th\u00e1i: $lead_name",
        "message_template": "Lead $lead_name \u0111\u00e3 chuy\u1ec3n t\u1eeb '$old_status' sang '$new_status'.",
    },
    "lead_created": {
        "title_template": "Lead m\u1edbi: $lead_name",
        "message_template": "H\u1ec7 th\u1ed1ng v\u1eeba t\u1ea1o lead m\u1edbi $lead_name t\u1eeb ngu\u1ed3n $source.",
    },
    "lead_deleted": {
        "title_template": "Lead b\u1ecb x\u00f3a",
        "message_template": "Lead $lead_name \u0111\u00e3 b\u1ecb x\u00f3a kh\u1ecfi h\u1ec7 th\u1ed1ng.",
    },
    "lead_restored": {
        "title_template": "Lead \u0111\u01b0\u1ee3c kh\u00f4i ph\u1ee5c",
        "message_template": "Lead $lead_name \u0111\u00e3 \u0111\u01b0\u1ee3c kh\u00f4i ph\u1ee5c l\u1ea1i.",
    },
    "lead_imported": {
        "title_template": "Import lead ho\u00e0n t\u1ea5t",
        "message_template": "\u0110\u00e3 import $total_imported lead t\u1eeb file $filename.",
    },
    "officer_availability_changed": {
        "title_template": "Officer \u0111\u1ed5i tr\u1ea1ng th\u00e1i s\u1eb5n s\u00e0ng",
        "message_template": "Officer $username \u0111\u00e3 \u0111\u1ed5i tr\u1ea1ng th\u00e1i t\u1eeb '$old_status' sang '$new_status'.",
    },
    "consultation_created": {
        "title_template": "T\u01b0 v\u1ea5n m\u1edbi cho lead #$lead_id",
        "message_template": "\u0110\u00e3 t\u1ea1o l\u1ecbch s\u1eed t\u01b0 v\u1ea5n m\u1edbi cho lead #$lead_id v\u1edbi tr\u1ea1ng th\u00e1i $status_id.",
    },
    "consultation_updated": {
        "title_template": "C\u1eadp nh\u1eadt t\u01b0 v\u1ea5n cho lead #$lead_id",
        "message_template": "T\u01b0 v\u1ea5n #$consultation_id \u0111\u00e3 \u0111\u1ed5i tr\u1ea1ng th\u00e1i t\u1eeb '$old_status_id' sang '$new_status_id'.",
    },
    "consultation_deleted": {
        "title_template": "X\u00f3a b\u1ea3n ghi t\u01b0 v\u1ea5n",
        "message_template": "B\u1ea3n ghi t\u01b0 v\u1ea5n #$consultation_id c\u1ee7a lead #$lead_id \u0111\u00e3 b\u1ecb x\u00f3a.",
    },
    "consultation_reminder": {
        "title_template": "Nh\u1eafc l\u1ecbch t\u01b0 v\u1ea5n: $lead_name",
        "message_template": "B\u1ea1n c\u00f3 l\u1ecbch t\u01b0 v\u1ea5n v\u1edbi $lead_name sau $minutes_until ph\u00fat.",
    },
    "application_created": {
        "title_template": "H\u1ed3 s\u01a1 m\u1edbi \u0111\u01b0\u1ee3c t\u1ea1o",
        "message_template": "H\u1ed3 s\u01a1 #$application_id v\u1eeba \u0111\u01b0\u1ee3c t\u1ea1o cho lead #$lead_id.",
    },
    "application_status_changed": {
        "title_template": "H\u1ed3 s\u01a1 \u0111\u1ed5i tr\u1ea1ng th\u00e1i",
        "message_template": "H\u1ed3 s\u01a1 #$application_id \u0111\u00e3 chuy\u1ec3n t\u1eeb '$old_status' sang '$new_status'.",
    },
    "application_deleted": {
        "title_template": "H\u1ed3 s\u01a1 b\u1ecb x\u00f3a",
        "message_template": "H\u1ed3 s\u01a1 #$application_id c\u1ee7a lead $lead_name \u0111\u00e3 b\u1ecb x\u00f3a.",
    },
    "payment_received": {
        "title_template": "\u0110\u00e3 ghi nh\u1eadn thanh to\u00e1n",
        "message_template": "H\u1ec7 th\u1ed1ng \u0111\u00e3 ghi nh\u1eadn thanh to\u00e1n #$payment_id v\u1edbi s\u1ed1 ti\u1ec1n $amount.",
    },
    "payment_verified": {
        "title_template": "Thanh to\u00e1n \u0111\u01b0\u1ee3c x\u00e1c nh\u1eadn",
        "message_template": "Thanh to\u00e1n #$payment_id \u0111\u00e3 \u0111\u01b0\u1ee3c x\u00e1c nh\u1eadn v\u1edbi s\u1ed1 ti\u1ec1n $amount.",
    },
    "ctv_claim_submitted": {
        "title_template": "CTV g\u1eedi claim m\u1edbi",
        "message_template": "CTV $collaborator_name v\u1eeba g\u1eedi claim cho lead $lead_name.",
    },
    "ctv_claim_approved": {
        "title_template": "Claim \u0111\u01b0\u1ee3c duy\u1ec7t",
        "message_template": "Claim #$claim_id cho lead $lead_name \u0111\u00e3 \u0111\u01b0\u1ee3c duy\u1ec7t.",
    },
    "ctv_claim_rejected": {
        "title_template": "Claim b\u1ecb t\u1eeb ch\u1ed1i",
        "message_template": "Claim #$claim_id cho lead $lead_name b\u1ecb t\u1eeb ch\u1ed1i. L\u00fd do: $rejection_reason.",
    },
    "ctv_approved": {
        "title_template": "T\u00e0i kho\u1ea3n CTV \u0111\u01b0\u1ee3c duy\u1ec7t",
        "message_template": "T\u00e0i kho\u1ea3n c\u1ed9ng t\u00e1c vi\u00ean $collaborator_name \u0111\u00e3 \u0111\u01b0\u1ee3c duy\u1ec7t.",
    },
    "ctv_suspended": {
        "title_template": "T\u00e0i kho\u1ea3n CTV b\u1ecb \u0111\u00ecnh ch\u1ec9",
        "message_template": "T\u00e0i kho\u1ea3n c\u1ed9ng t\u00e1c vi\u00ean $collaborator_name \u0111\u00e3 b\u1ecb \u0111\u00ecnh ch\u1ec9. L\u00fd do: $reason.",
    },
    "ctv_commission_created": {
        "title_template": "Ph\u00e1t sinh hoa h\u1ed3ng m\u1edbi",
        "message_template": "B\u1ea1n c\u00f3 kho\u1ea3n hoa h\u1ed3ng m\u1edbi #$commission_id v\u1edbi s\u1ed1 ti\u1ec1n $amount.",
    },
    "ctv_attribution_expiring": {
        "title_template": "Quy\u1ec1n gi\u1edbi thi\u1ec7u s\u1eafp h\u1ebft h\u1ea1n",
        "message_template": "Quy\u1ec1n gi\u1edbi thi\u1ec7u lead #$lead_id s\u1ebd h\u1ebft h\u1ea1n sau $days_remaining ng\u00e0y.",
    },
    "ctv_attribution_expired": {
        "title_template": "Quy\u1ec1n gi\u1edbi thi\u1ec7u \u0111\u00e3 h\u1ebft h\u1ea1n",
        "message_template": "Quy\u1ec1n gi\u1edbi thi\u1ec7u cho lead #$lead_id \u0111\u00e3 h\u1ebft h\u1ea1n.",
    },
    "ctv_weekly_summary": {
        "title_template": "B\u00e1o c\u00e1o tu\u1ea7n c\u1ed9ng t\u00e1c vi\u00ean",
        "message_template": "Tu\u1ea7n $week: $new_leads lead m\u1edbi, $commissions hoa h\u1ed3ng, t\u1ed5ng thu nh\u1eadp $total_earnings.",
    },
    "system_alert": {
        "title_template": "C\u1ea3nh b\u00e1o h\u1ec7 th\u1ed1ng: $severity",
        "message_template": "$message",
    },
    "holiday_calendar_incomplete": {
        "title_template": "L\u1ecbch ngh\u1ec9 l\u1ec5 ch\u01b0a \u0111\u1ea7y \u0111\u1ee7",
        "message_template": "$message (n\u0103m $year).",
    },
    "system_announcement": {
        "title_template": "$title",
        "message_template": "$message",
    },
    "user_role_changed": {
        "title_template": "Vai tr\u00f2 t\u00e0i kho\u1ea3n thay \u0111\u1ed5i",
        "message_template": "T\u00e0i kho\u1ea3n c\u1ee7a b\u1ea1n \u0111\u00e3 \u0111\u1ed5i t\u1eeb '$old_role' sang '$new_role'.",
    },
    "user_deactivated": {
        "title_template": "T\u00e0i kho\u1ea3n b\u1ecb v\u00f4 hi\u1ec7u h\u00f3a",
        "message_template": "T\u00e0i kho\u1ea3n $username \u0111\u00e3 b\u1ecb v\u00f4 hi\u1ec7u h\u00f3a. L\u00fd do: $reason.",
    },
    "user_profile_updated": {
        "title_template": "H\u1ed3 s\u01a1 c\u1ee7a b\u1ea1n \u0111\u00e3 \u0111\u01b0\u1ee3c c\u1eadp nh\u1eadt",
        "message_template": "Admin \u0111\u00e3 c\u1eadp nh\u1eadt h\u1ed3 s\u01a1 c\u1ee7a b\u1ea1n. Tr\u01b0\u1eddng thay \u0111\u1ed5i: $updated_fields.",
    },
    "pipeline_config_updated": {
        "title_template": "C\u1eadp nh\u1eadt c\u1ea5u h\u00ecnh pipeline",
        "message_template": "C\u1ea5u h\u00ecnh $config_type \u0111\u00e3 \u0111\u01b0\u1ee3c $operation tr\u00ean t\u00e0i nguy\u00ean $resource_id.",
    },
    "suspicious_login": {
        "title_template": "\u0110\u0103ng nh\u1eadp \u0111\u00e1ng ng\u1edd",
        "message_template": "Ph\u00e1t hi\u1ec7n \u0111\u0103ng nh\u1eadp \u0111\u00e1ng ng\u1edd t\u1eeb IP $ip_address t\u1ea1i $location.",
    },
}


_ZNS_DRAFTS: list[TemplateSeed] = [
    TemplateSeed(
        name="ZNS Draft - Payment Verified v1",
        template_code="ZNS_PAYMENT_VERIFIED_V1",
        description="Draft mapping for external applicant notification when payment is verified.",
        title_template="Thanh to\u00e1n \u0111\u01b0\u1ee3c x\u00e1c nh\u1eadn",
        message_template="Thanh to\u00e1n #$payment_id \u0111\u00e3 \u0111\u01b0\u1ee3c x\u00e1c nh\u1eadn v\u1edbi s\u1ed1 ti\u1ec1n $amount.",
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
        title_template="H\u1ed3 s\u01a1 thay \u0111\u1ed5i tr\u1ea1ng th\u00e1i",
        message_template="H\u1ed3 s\u01a1 #$application_id \u0111\u00e3 chuy\u1ec3n sang tr\u1ea1ng th\u00e1i '$new_status'.",
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
        title_template="Nh\u1eafc l\u1ecbch t\u01b0 v\u1ea5n $booking_code",
        message_template=(
            "Nh\u1eafc b\u1ea1n l\u1ecbch t\u01b0 v\u1ea5n $lead_name "
            "(m\u00e3 $lead_code, ng\u00e0nh $major_name) "
            "v\u00e0o $scheduled_time_vn (sau $minutes_until ph\u00fat)."
        ),
        link_template=None,
        # Must mirror payload contract at
        # app/services/notification_payloads.py:for_consultation_reminder +
        # app/core/event_catalog.py CONSULTATION_REMINDER variables. Workbook
        # generator renders `required_variables` from this list (line 493)
        # so stale keys here surface as mis-mappings in admin intake sheets.
        variables=[
            "consultation_id",
            "lead_id",
            "lead_name",
            "lead_phone",
            "officer_id",
            "scheduled_at",
            "minutes_until",
            "scheduled_time_vn",
            "booking_code",
            "lead_code",
            "major_name",
        ],
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
