from app.core.rate_limits import limiter, RateLimits
# app/routers/notification_rules.py
"""
✅ PHASE 2.2: Notification Rules CRUD Router

Admin-only API endpoints for managing notification rules.
Allows administrators to create, read, update, and delete notification
rules through UI instead of modifying code.

REFACTORED: CRUD logic moved to notification_rule_crud_service.py
Router now only handles HTTP concerns and orchestration.
"""
from typing import Optional, Dict, Any, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from .. import database, models, schemas
from ..config import settings
from app.core.deps import CasbinAuth, get_notification_rule_for_admin  # Phase 2.2
from ..core.event_catalog import get_notifiable_events
from ..services import notification_rule_crud_service
from ..repositories import NotificationTemplateRepository
from ..utils.exceptions import BadRequest

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/notification-rules", tags=["Notification Rules (Admin)"])

# Admin-only permission dependency


# =============================================================================
# ✅ NOTIFICATION 2.0 - PHASE 2: Metadata API
# =============================================================================

class ResolverTypeOption(BaseModel):
    """Option for resolver type selector"""
    value: str
    label: str
    description: str


class OperatorOption(BaseModel):
    """Option for condition operator selector"""
    value: str
    label: str


class ChannelInfo(BaseModel):
    """Channel with live/planned status.

    v5 pre-work: ``internal_only`` distinguishes channels that target staff
    only (e.g. zalo_bot) from public-facing channels (browser/email/zalo/sms).
    External recipient pickers must hide ``internal_only=True`` channels to
    prevent leaking staff infrastructure to leads/customers.
    """
    value: str
    status: str  # "live" | "planned"
    internal_only: bool = False


class ExternalResolverTypeOption(BaseModel):
    """External recipient resolver option for Zalo/SMS delivery"""
    value: str
    label: str
    description: str


class MetadataResponse(BaseModel):
    """Complete metadata for building notification rules dynamically"""
    events: List[Dict[str, Any]]
    channels: List[ChannelInfo]
    resolver_types: List[ResolverTypeOption]
    external_resolver_types: List[ExternalResolverTypeOption]
    operators: List[OperatorOption]
    existing_rule_events: List[str] = []  # Events that already have a DB rule (for duplicate warning)


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/metadata", response_model=MetadataResponse)
async def get_notification_metadata(
    request: Request,
    current_admin: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """
    ✅ NOTIFICATION 2.0 - PHASE 2: Get metadata for notification rule builder.

    Returns all metadata needed for frontend to dynamically build notification rules:
        - Event definitions with variables and filter fields
        - Available channels
        - Resolver types
        - Condition operators

    This makes the frontend completely dynamic - no hardcoding needed.
    """
    log.info("Fetching notification metadata", admin_id=current_admin.id)

    # PR1: Serve from event_catalog — only "user" classification events
    notifiable = get_notifiable_events()
    events_list = [
        {
            "event": d.event.value,
            "display_name": d.display_name,
            "description": d.description,
            "variables": [
                {"name": v.name, "type": v.type, "description": v.description, "required": v.required}
                for v in d.variables
            ],
            "filter_fields": [v.name for v in d.variables if v.required],
            "default_channels": list(d.default_channels),
            "category": d.category,
            "condition_fields": [
                {"path": cf.path, "type": cf.type, "description": cf.description, "operators": list(cf.operators)}
                for cf in d.condition_fields
            ],
            "allowed_resolvers": list(d.allowed_resolvers),
            "link_strategy": d.link_strategy,
        }
        for d in notifiable
    ]

    return {
        "events": events_list,
        "channels": [
            {"value": "browser", "status": "live"},
            {"value": "email", "status": "live"},
            {"value": "zalo", "status": "live" if settings.ZALO_ENABLED else "planned"},
            # v5 Step 17: zalo_bot is internal_only=True so the FE wizard
            # hides it from external recipient pickers. Status follows
            # the env flag — "planned" until ZALO_BOT_ENABLED flips on
            # in production, then "live".
            {
                "value": "zalo_bot",
                "status": "live" if settings.ZALO_BOT_ENABLED else "planned",
                "internal_only": True,
            },
            {"value": "sms", "status": "planned"},
        ],
        "resolver_types": [
            {
                "value": "lead_owner",
                "label": "Lead Owner",
                "description": "Gửi cho officer được assign lead"
            },
            {
                "value": "unit_staff",
                "label": "Unit Staff",
                "description": "Gửi cho tất cả staff trong đơn vị"
            },
            {
                "value": "unit_managers",
                "label": "Unit Managers",
                "description": "Gửi cho managers/admins của đơn vị"
            },
            {
                "value": "all_users",
                "label": "All Users",
                "description": "Gửi cho tất cả users"
            },
            {
                "value": "all_admins",
                "label": "All Admins",
                "description": "Gửi cho tất cả admins"
            },
            {
                "value": "specific_users",
                "label": "Specific Users",
                "description": "Gửi cho danh sách user cụ thể"
            },
            {
                "value": "collaborator_user",
                "label": "Collaborator User",
                "description": "Gửi cho user liên kết với cộng tác viên"
            }
        ],
        "external_resolver_types": [
            {
                "value": "lead_contact",
                "label": "Lead (qua Zalo/SMS)",
                "description": "Gửi cho lead qua số điện thoại/Zalo"
            },
            {
                "value": "admission_contact",
                "label": "Hồ sơ tuyển sinh (qua Zalo/SMS)",
                "description": "Gửi cho ứng viên qua số điện thoại/Zalo"
            },
            {
                "value": "collaborator_contact",
                "label": "Cộng tác viên (qua Zalo/SMS)",
                "description": "Gửi cho cộng tác viên qua số điện thoại/Zalo"
            }
        ],
        "operators": [
            {"value": "eq", "label": "Equals (=)"},
            {"value": "ne", "label": "Not Equals (≠)"},
            {"value": "gt", "label": "Greater Than (>)"},
            {"value": "gte", "label": "Greater Than or Equal (≥)"},
            {"value": "lt", "label": "Less Than (<)"},
            {"value": "lte", "label": "Less Than or Equal (≤)"},
            {"value": "in", "label": "In List"},
            {"value": "not_in", "label": "Not In List"},
            {"value": "contains", "label": "Contains"},
        ],
        "existing_rule_events": [
            row[0] for row in (
                await db.execute(
                    select(models.NotificationRule.event).distinct()
                )
            ).all()
        ],
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.post("/preview", response_model=schemas.NotificationRulePreviewResponse)
async def preview_notification_rule(
    request: Request,
    rule_data: schemas.NotificationRulePreview,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    PR2: Render preview of notification content for each action/branch.

    Frontend sends sample_payload with concrete values for template variables.
    Backend renders templates and returns per-action previews with code-owned link.
    Preview output is plain text — no HTML rendering.
    """
    from string import Template
    from app.core.event_catalog import get_event_by_key, render_link

    definition = get_event_by_key(rule_data.event)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown event: {rule_data.event}",
        )
    if definition.notification_class != "user":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Event '{rule_data.event}' is not a configurable user event.",
        )

    payload = rule_data.sample_payload
    link = render_link(definition.event, payload)

    previews = []
    for action in rule_data.actions or []:
        mode = action.content_mode or "inherit_default"

        if mode == "inline_override" and action.content_override:
            title = Template(action.content_override.get("title_template", "")).safe_substitute(payload)
            message = Template(action.content_override.get("message_template", "")).safe_substitute(payload)
        elif mode == "template_override" and action.template_code:
            # Lookup real template content for preview
            tpl = await NotificationTemplateRepository(db).get_by_template_code(
                action.template_code
            )
            if tpl:
                title = Template(tpl.title_template).safe_substitute(payload)
                message = Template(tpl.message_template).safe_substitute(payload)
            else:
                title = f"[Template not found: {action.template_code}]"
                message = ""
        else:
            title = Template(rule_data.title_template).safe_substitute(payload)
            message = Template(rule_data.message_template).safe_substitute(payload)

        previews.append({
            "step": action.step,
            "channel": action.channel,
            "branch_key": action.branch_key,
            "rendered_title": title,
            "rendered_message": message,
            "rendered_link": link,
            "content_mode": mode,
            "delay_minutes": action.delay_minutes or 0,
        })

    # If no actions provided, render a single default preview
    if not previews:
        previews.append({
            "step": 1,
            "channel": "browser",
            "branch_key": None,
            "rendered_title": Template(rule_data.title_template).safe_substitute(payload),
            "rendered_message": Template(rule_data.message_template).safe_substitute(payload),
            "rendered_link": link,
            "content_mode": "inherit_default",
            "delay_minutes": 0,
        })

    return {
        "event": rule_data.event,
        "link_strategy": definition.link_strategy,
        "rendered_link": link,
        "actions": previews,
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.NotificationRulesPage)
async def list_notification_rules(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event: Optional[str] = Query(None, description="Filter by event type"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
):
    """
    (Admin only) Get paginated list of notification rules.

    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 50, max: 100)
        - event: Filter by event type (e.g., "LEAD_ASSIGNED")
        - enabled: Filter by enabled status (true/false)

    Returns:
        Paginated list of notification rules with total count
    """
    skip = (page - 1) * page_size

    rules, total = await notification_rule_crud_service.get_rules(
        db=db,
        skip=skip,
        limit=page_size,
        event=event,
        enabled=enabled,
    )

    log.info(
        "Listed notification rules",
        admin_id=current_admin.id,
        page=page,
        page_size=page_size,
        total=total,
        filters={"event": event, "enabled": enabled}
    )

    return {
        "total_count": total,
        "rules": rules
    }


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/{rule_id}", response_model=schemas.NotificationRule)
async def get_notification_rule(
    request: Request,
    rule: models.NotificationRule = Depends(get_notification_rule_for_admin),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get a specific notification rule by ID.

    Returns:
        NotificationRule with all details (including actions)
    """
    log.info(
        "Retrieved notification rule",
        rule_id=rule.id,
        event_type=rule.event,
        admin_id=current_admin.id
    )

    return rule


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("", response_model=schemas.NotificationRule, status_code=status.HTTP_201_CREATED)
async def create_notification_rule(
    request: Request,
    rule_data: schemas.NotificationRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Create a new notification rule.

    Body:
        NotificationRuleCreate schema with:
        - event: SystemEvents enum value
        - title_template: Template with {placeholders}
        - message_template: Message template
        - notification_type: Severity (info/success/warning/error)
        - link_template: Optional link template
        - channels: ["browser", "email", "sms"]
        - recipient_config: Resolver configuration
        - condition: Optional activation conditions
        - enabled: Enable/disable flag

    Returns:
        Created NotificationRule
    """
    try:
        rule, callback = await notification_rule_crud_service.create_rule(
            db=db,
            rule_data=rule_data,
        )

        # ✅ TRANSACTION PATTERN: Commit and execute callback
        await db.commit()
        await callback()

        # Reload with actions relationship to avoid MissingGreenlet on
        # response serialization. db.refresh() only refreshes scalars;
        # we need selectinload for the actions collection.
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload
        reloaded = (await db.execute(
            sa_select(models.NotificationRule)
            .where(models.NotificationRule.id == rule.id)
            .options(selectinload(models.NotificationRule.actions))
        )).scalar_one()
        return reloaded

    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("/{rule_id}", response_model=schemas.NotificationRule)
async def update_notification_rule(
    request: Request,
    rule_update: schemas.NotificationRuleUpdate,
    rule: models.NotificationRule = Depends(get_notification_rule_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Update an existing notification rule.

    Supports partial updates - only provided fields will be updated.

    Body:
        NotificationRuleUpdate schema (all fields optional)

    Returns:
        Updated NotificationRule
    """
    updated_rule, callback = await notification_rule_crud_service.update_rule(
        db=db,
        rule=rule,
        rule_update=rule_update,
    )

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    return updated_rule


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.patch("/{rule_id}/toggle", response_model=schemas.NotificationRule)
async def toggle_notification_rule(
    request: Request,
    rule: models.NotificationRule = Depends(get_notification_rule_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Toggle enabled/disabled status of a notification rule.

    This is a convenience endpoint for quickly enabling/disabling rules
    without needing to send the full update payload.

    Returns:
        Updated NotificationRule with toggled enabled status
    """
    toggled_rule, callback = await notification_rule_crud_service.toggle_rule(
        db=db,
        rule=rule,
    )

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    return toggled_rule


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_rule(
    request: Request,
    rule: models.NotificationRule = Depends(get_notification_rule_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Delete a notification rule.

    WARNING: This permanently deletes the rule. Consider disabling
    the rule instead if you might need it later.

    Returns:
        No content (204)
    """
    _, callback = await notification_rule_crud_service.delete_rule(
        db=db,
        rule=rule,
    )

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    return None
