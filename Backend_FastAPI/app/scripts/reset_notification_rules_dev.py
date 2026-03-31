"""
Backup current notification rules and reseed a curated dev-safe ruleset.

Usage:
    python -m app.scripts.reset_notification_rules_dev

What this script does:
1. Backs up all current notification rules + actions to JSON
2. Upserts a curated wizard-friendly ruleset
3. Disables legacy rules that are not part of the curated set
4. Creates disabled tombstones for registry-backed events that should stay off
5. Recalculates NotificationTemplate.usage_count
6. Invalidates per-event rule cache keys
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.services.notification_registry import NOTIFICATION_REGISTRY
from app.services.notification_rule_loader import invalidate_rule_cache

log = structlog.get_logger(__name__)


def _internal_group(
    resolver_type: str,
    channels: list[str],
) -> dict[str, Any]:
    return {
        "recipient_config": {"resolver_type": resolver_type, "params": {}},
        "channels": channels,
    }


def _build_rule(
    *,
    event: str,
    title_template: str,
    message_template: str,
    notification_type: str,
    groups: list[dict[str, Any]],
    link_template: str | None = None,
    condition: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    channels: list[str] = []
    actions: list[dict[str, Any]] = []
    step = 1

    for group_index, group in enumerate(groups, start=1):
        recipient_config = deepcopy(group["recipient_config"])
        for channel in group["channels"]:
            if channel not in channels:
                channels.append(channel)
            actions.append(
                {
                    "step": step,
                    "channel": channel,
                    "template_code": None,
                    "delay_minutes": 0,
                    "config": None,
                    "recipient_config": deepcopy(recipient_config),
                    "content_mode": "inherit_default",
                    "content_override": None,
                    "branch_key": f"group_{group_index}_{channel}",
                }
            )
            step += 1

    return {
        "event": event,
        "title_template": title_template,
        "message_template": message_template,
        "notification_type": notification_type,
        "link_template": link_template,
        "channels": channels,
        "recipient_config": deepcopy(groups[0]["recipient_config"]),
        "condition": condition,
        "enabled": enabled,
        "template_id": None,
        "actions": actions,
    }


CURATED_RULES: dict[str, dict[str, Any]] = {
    "lead_created": _build_rule(
        event="lead_created",
        title_template="Lead mới: $lead_name",
        message_template="Lead $lead_name vừa được tạo từ nguồn $source. Vui lòng kiểm tra và phân công xử lý.",
        notification_type="info",
        link_template="/leads/$lead_id",
        groups=[_internal_group("unit_managers", ["browser"])],
    ),
    "lead_assigned": _build_rule(
        event="lead_assigned",
        title_template="Lead được phân công: $lead_name",
        message_template="Bạn vừa được phân công lead $lead_name ($lead_phone). Vui lòng liên hệ sớm.",
        notification_type="success",
        link_template="/leads/$lead_id",
        groups=[_internal_group("lead_owner", ["browser", "email"])],
    ),
    "lead_assignment_failed": _build_rule(
        event="lead_assignment_failed",
        title_template="Cảnh báo: phân công lead thất bại",
        message_template="Lead $lead_name chưa thể phân công tự động. Lý do: $reason.",
        notification_type="warning",
        link_template="/leads/$lead_id",
        groups=[_internal_group("unit_managers", ["browser", "email"])],
    ),
    "lead_status_changed": _build_rule(
        event="lead_status_changed",
        title_template="Lead cập nhật trạng thái: $lead_name",
        message_template="Lead $lead_name đã chuyển từ $old_status sang $new_status.",
        notification_type="info",
        link_template="/leads/$lead_id",
        groups=[_internal_group("lead_owner", ["browser"])],
    ),
    "consultation_created": _build_rule(
        event="consultation_created",
        title_template="Có lịch tư vấn mới cho lead #$lead_id",
        message_template="Lịch tư vấn mới vừa được tạo cho lead #$lead_id. Vui lòng kiểm tra thông tin tư vấn.",
        notification_type="info",
        link_template="/leads/$lead_id?tab=consultations",
        groups=[
            _internal_group("lead_owner", ["browser"]),
            _internal_group("unit_managers", ["browser"]),
        ],
    ),
    "consultation_reminder": _build_rule(
        event="consultation_reminder",
        title_template="Nhắc lịch tư vấn với $lead_name",
        message_template="Bạn có lịch tư vấn với $lead_name ($lead_phone) trong $minutes_until phút nữa.",
        notification_type="info",
        link_template="/leads/$lead_id",
        groups=[_internal_group("lead_owner", ["browser"])],
    ),
    "application_created": _build_rule(
        event="application_created",
        title_template="Có hồ sơ mới: #$application_id",
        message_template="Hồ sơ #$application_id của $lead_name vừa được tạo cho chương trình $major_program_name.",
        notification_type="success",
        link_template="/admissions/$application_id",
        groups=[
            _internal_group("lead_owner", ["browser", "email"]),
            _internal_group("all_admins", ["browser", "email"]),
        ],
    ),
    "application_deleted": _build_rule(
        event="application_deleted",
        title_template="Hồ sơ đã bị xóa: #$application_id",
        message_template="Hồ sơ #$application_id của $lead_name đã bị xóa.",
        notification_type="warning",
        link_template="/leads/$lead_id",
        groups=[
            _internal_group("lead_owner", ["browser", "email"]),
            _internal_group("all_admins", ["browser", "email"]),
        ],
    ),
    "application_status_changed": _build_rule(
        event="application_status_changed",
        title_template="Hồ sơ cập nhật trạng thái: #$application_id",
        message_template="Hồ sơ #$application_id đã chuyển từ $old_status sang $new_status.",
        notification_type="info",
        link_template="/admissions/$application_id",
        groups=[
            _internal_group("lead_owner", ["browser", "email"]),
            _internal_group("all_admins", ["browser", "email"]),
        ],
    ),
    "payment_received": _build_rule(
        event="payment_received",
        title_template="Thanh toán mới được ghi nhận",
        message_template="Khoản thanh toán $amount ($payment_type) đã được ghi nhận, đang chờ xác nhận.",
        notification_type="info",
        link_template="/finance/payments/$payment_id",
        groups=[_internal_group("specific_users", ["browser", "email"])],
    ),
    "payment_verified": _build_rule(
        event="payment_verified",
        title_template="Thanh toán đã được xác nhận",
        message_template="Khoản thanh toán $amount cho hồ sơ liên quan đã được xác nhận thành công.",
        notification_type="success",
        link_template="/finance/payments/$payment_id",
        groups=[_internal_group("specific_users", ["browser", "email"])],
    ),
    "system_alert": _build_rule(
        event="system_alert",
        title_template="[${severity}] Cảnh báo hệ thống",
        message_template="$message",
        notification_type="warning",
        link_template="$action_url",
        groups=[_internal_group("all_users", ["browser", "email"])],
    ),
    "system_announcement": _build_rule(
        event="system_announcement",
        title_template="$title",
        message_template="$message",
        notification_type="info",
        groups=[_internal_group("all_users", ["browser", "email"])],
    ),
    "holiday_calendar_incomplete": _build_rule(
        event="holiday_calendar_incomplete",
        title_template="Lịch nghỉ lễ năm $year chưa đầy đủ",
        message_template="$message",
        notification_type="warning",
        link_template="$action_url",
        groups=[_internal_group("all_admins", ["browser"])],
    ),
    "user_role_changed": _build_rule(
        event="user_role_changed",
        title_template="Vai trò tài khoản đã thay đổi",
        message_template="Vai trò của bạn đã thay đổi từ $old_role sang $new_role.",
        notification_type="info",
        link_template="/profile",
        groups=[_internal_group("specific_users", ["browser", "email"])],
    ),
    "user_deactivated": _build_rule(
        event="user_deactivated",
        title_template="Tài khoản đã bị vô hiệu hóa",
        message_template="Tài khoản của bạn đã bị vô hiệu hóa. Lý do: $reason.",
        notification_type="error",
        groups=[_internal_group("specific_users", ["browser"])],
    ),
    "suspicious_login": _build_rule(
        event="suspicious_login",
        title_template="Đăng nhập đáng ngờ từ thiết bị lạ",
        message_template="Phát hiện đăng nhập từ $location ($device). Nếu không phải bạn, hãy đổi mật khẩu ngay.",
        notification_type="warning",
        link_template="/settings/login-history",
        groups=[_internal_group("specific_users", ["browser", "email"])],
    ),
    "ctv_claim_submitted": _build_rule(
        event="ctv_claim_submitted",
        title_template="CTV gửi claim mới",
        message_template="$collaborator_name vừa gửi claim cho lead $lead_name.",
        notification_type="info",
        link_template="/admin/collaborators/claims/$claim_id",
        groups=[_internal_group("unit_managers", ["browser"])],
    ),
    "ctv_claim_approved": _build_rule(
        event="ctv_claim_approved",
        title_template="Claim đã được duyệt",
        message_template="Claim #$claim_id của bạn đã được duyệt.",
        notification_type="success",
        link_template="/ctv/claims",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_claim_rejected": _build_rule(
        event="ctv_claim_rejected",
        title_template="Claim bị từ chối",
        message_template="Claim #$claim_id đã bị từ chối. Lý do: $rejection_reason",
        notification_type="warning",
        link_template="/ctv/claims",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_approved": _build_rule(
        event="ctv_approved",
        title_template="Tài khoản cộng tác viên đã được duyệt",
        message_template="Tài khoản cộng tác viên của bạn đã được duyệt. Bạn có thể bắt đầu giới thiệu lead.",
        notification_type="success",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_suspended": _build_rule(
        event="ctv_suspended",
        title_template="Tài khoản cộng tác viên bị đình chỉ",
        message_template="Tài khoản cộng tác viên của bạn đã bị đình chỉ. Vui lòng liên hệ quản lý để biết thêm chi tiết.",
        notification_type="error",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_commission_created": _build_rule(
        event="ctv_commission_created",
        title_template="Bạn có hoa hồng mới",
        message_template="Bạn nhận được hoa hồng $amount VND cho lead #$lead_id.",
        notification_type="success",
        link_template="/ctv/commissions",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_attribution_expiring": _build_rule(
        event="ctv_attribution_expiring",
        title_template="Quyền giới thiệu sắp hết hạn",
        message_template="Quyền giới thiệu cho lead #$lead_id sẽ hết hạn trong $days_remaining ngày.",
        notification_type="warning",
        link_template="/ctv/leads",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
    "ctv_attribution_expired": _build_rule(
        event="ctv_attribution_expired",
        title_template="Quyền giới thiệu đã hết hạn",
        message_template="Quyền giới thiệu cho lead #$lead_id đã hết hạn.",
        notification_type="warning",
        link_template="/ctv/leads",
        groups=[_internal_group("collaborator_user", ["browser", "email"])],
    ),
}


def _disabled_tombstone(event_name: str) -> dict[str, Any]:
    return {
        "event": event_name,
        "title_template": f"[LEGACY DISABLED] {event_name}",
        "message_template": "Rule cũ đã được tắt trong đợt reset cấu hình notification.",
        "notification_type": "info",
        "link_template": None,
        "channels": ["browser"],
        "recipient_config": {"resolver_type": "all_admins", "params": {}},
        "condition": None,
        "enabled": False,
        "template_id": None,
        "actions": [
            {
                "step": 1,
                "channel": "browser",
                "template_code": None,
                "delay_minutes": 0,
                "config": None,
                "recipient_config": {"resolver_type": "all_admins", "params": {}},
                "content_mode": "inherit_default",
                "content_override": None,
                "branch_key": "group_1_browser",
            }
        ],
    }


def _serialize_rule(rule: models.NotificationRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "event": rule.event,
        "title_template": rule.title_template,
        "message_template": rule.message_template,
        "notification_type": rule.notification_type,
        "link_template": rule.link_template,
        "channels": rule.channels,
        "recipient_config": rule.recipient_config,
        "condition": rule.condition,
        "enabled": rule.enabled,
        "template_id": rule.template_id,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        "actions": [
            {
                "id": action.id,
                "step": action.step,
                "channel": action.channel,
                "template_code": action.template_code,
                "delay_minutes": action.delay_minutes,
                "config": action.config,
                "recipient_config": action.recipient_config,
                "content_mode": action.content_mode,
                "content_override": action.content_override,
                "branch_key": action.branch_key,
            }
            for action in sorted(rule.actions, key=lambda item: item.step)
        ],
    }


def _apply_rule_payload(rule: models.NotificationRule, payload: dict[str, Any]) -> None:
    rule.title_template = payload["title_template"]
    rule.message_template = payload["message_template"]
    rule.notification_type = payload["notification_type"]
    rule.link_template = payload["link_template"]
    rule.channels = payload["channels"]
    rule.recipient_config = deepcopy(payload["recipient_config"])
    rule.condition = deepcopy(payload["condition"])
    rule.enabled = payload["enabled"]
    rule.template_id = payload["template_id"]


async def _replace_actions(
    session,
    rule_id: int,
    actions: list[dict[str, Any]],
) -> None:
    await session.execute(
        delete(models.NotificationAction).where(
            models.NotificationAction.rule_id == rule_id
        )
    )
    for action in actions:
        session.add(
            models.NotificationAction(
                rule_id=rule_id,
                step=action["step"],
                channel=action["channel"],
                template_code=action["template_code"],
                delay_minutes=action["delay_minutes"],
                config=deepcopy(action["config"]),
                recipient_config=deepcopy(action["recipient_config"]),
                content_mode=action["content_mode"],
                content_override=deepcopy(action["content_override"]),
                branch_key=action["branch_key"],
            )
        )


async def _recalculate_template_usage(session) -> None:
    await session.execute(
        update(models.NotificationTemplate).values(usage_count=0)
    )
    result = await session.execute(
        select(
            models.NotificationRule.template_id,
            func.count(models.NotificationRule.id),
        )
        .where(models.NotificationRule.template_id.is_not(None))
        .group_by(models.NotificationRule.template_id)
    )
    for template_id, usage_count in result.all():
        await session.execute(
            update(models.NotificationTemplate)
            .where(models.NotificationTemplate.id == template_id)
            .values(usage_count=usage_count)
        )


async def reset_notification_rules_dev() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    repo_root = Path(__file__).resolve().parents[2]
    backup_dir = repo_root / "backups" / "notification_rules"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"notification_rules_backup_{timestamp}.json"

    touched_events: set[str] = set()

    async with async_session() as session:
        result = await session.execute(
            select(models.NotificationRule)
            .options(selectinload(models.NotificationRule.actions))
            .order_by(models.NotificationRule.event, models.NotificationRule.id)
        )
        existing_rules = list(result.scalars().all())
        existing_by_event = {rule.event: rule for rule in existing_rules}

        backup_payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rule_count": len(existing_rules),
            "rules": [_serialize_rule(rule) for rule in existing_rules],
        }
        backup_path.write_text(
            json.dumps(backup_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        registry_events = {event.value for event in NOTIFICATION_REGISTRY}
        target_events = registry_events | set(CURATED_RULES.keys()) | set(existing_by_event.keys())

        created_count = 0
        updated_count = 0
        disabled_count = 0

        for event_name in sorted(target_events):
            payload = CURATED_RULES.get(event_name)
            if payload is None:
                payload = _disabled_tombstone(event_name)

            existing_rule = existing_by_event.get(event_name)
            if existing_rule is None:
                existing_rule = models.NotificationRule(event=event_name)
                _apply_rule_payload(existing_rule, payload)
                session.add(existing_rule)
                await session.flush()
                created_count += 1
            else:
                _apply_rule_payload(existing_rule, payload)
                updated_count += 1

            await _replace_actions(session, existing_rule.id, payload["actions"])
            touched_events.add(event_name)

            if not payload["enabled"]:
                disabled_count += 1

        await _recalculate_template_usage(session)
        await session.commit()

    for event_name in touched_events:
        await invalidate_rule_cache(event_name)

    await engine.dispose()

    enabled_count = len(CURATED_RULES)
    legacy_disabled = disabled_count
    log.info(
        "Notification rules reset complete",
        backup_path=str(backup_path),
        enabled_rules=enabled_count,
        disabled_rules=legacy_disabled,
        touched_events=len(touched_events),
        created=created_count,
        updated=updated_count,
    )
    print(
        json.dumps(
            {
                "backup_path": str(backup_path),
                "enabled_rules": enabled_count,
                "disabled_rules": legacy_disabled,
                "touched_events": len(touched_events),
                "created": created_count,
                "updated": updated_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(reset_notification_rules_dev())
