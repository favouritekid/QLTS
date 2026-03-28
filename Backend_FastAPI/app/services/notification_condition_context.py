# app/services/notification_condition_context.py
"""
Evaluation context builder for notification rule conditions.

Separates two concerns:
1. Projection: build nested dict structure from existing payload (zero cost)
2. Enrichment: query DB for fields not in payload (only when needed)
"""
import logging
from typing import Any, Dict, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import SystemEvents

log = logging.getLogger(__name__)

# Fields that can be projected from payload without DB lookup
_PAYLOAD_PROJECTABLE = {
    "actor.id": "actor_id",
    "actor.name": "actor_name",
    "lead.id": "lead_id",
    "lead.name": "lead_name",
    "lead.officer_id": "officer_id",
    "consultation.id": "consultation_id",
}

# Fields that ALWAYS require DB enrichment
_ENRICHMENT_FIELDS = {
    "actor": {"actor.role", "actor.unit_id"},
    "lead": {"lead.source", "lead.consultation_status_id", "lead.stage_id", "lead.unit_id"},
    "consultation": {"consultation.status_id"},
}

# event.* mapping: payload flat key -> context nested key
_EVENT_PROJECTION_MAP = {
    "old_status": "old_status_id",
    "new_status": "new_status_id",
    "old_stage": "old_stage_id",
    "new_stage": "new_stage_id",
    "updated_fields": "updated_fields",
    "status_changed": "status_changed",
    "unit_id": "unit_id",
    "total_imported": "total_imported",
    "filename": "filename",
    "minutes_until": "minutes_until",
    "scheduled_at": "scheduled_at",
    "reason": "reason",
    "old_unit_id": "old_unit_id",
    "new_unit_id": "new_unit_id",
}


def analyze_condition(condition: dict | None) -> Tuple[Set[str], Set[str]]:
    """
    Scan condition tree (recursive for compound).
    Returns (projection_ns, enrichment_ns).
    """
    if not condition:
        return set(), set()

    projection_ns: Set[str] = set()
    enrichment_ns: Set[str] = set()

    _scan_condition(condition, projection_ns, enrichment_ns)
    return projection_ns, enrichment_ns


def _scan_condition(condition: dict, proj: Set[str], enrich: Set[str]) -> None:
    """Recursively scan condition tree for namespace requirements."""
    if "conditions" in condition:
        for sub in condition.get("conditions", []):
            _scan_condition(sub, proj, enrich)
        return

    field = condition.get("field", "")
    if not field or "." not in field:
        return  # flat field, no namespace needed

    namespace = field.split(".")[0]
    proj.add(namespace)

    # Check if this field needs DB enrichment
    if field not in _PAYLOAD_PROJECTABLE:
        enrich_fields = _ENRICHMENT_FIELDS.get(namespace, set())
        if field in enrich_fields:
            enrich.add(namespace)


async def build_evaluation_context(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    projection_ns: Set[str],
    enrichment_ns: Set[str],
) -> dict:
    """Build nested evaluation context from flat payload + optional DB enrichment."""
    if not projection_ns and not enrichment_ns:
        return payload

    context: Dict[str, Any] = {**payload}

    # Build event namespace (pure projection, never needs enrichment)
    if "event" in projection_ns:
        event_ns = {}
        for payload_key, context_key in _EVENT_PROJECTION_MAP.items():
            if payload_key in payload:
                event_ns[context_key] = payload[payload_key]
        context["event"] = event_ns

    # Build actor namespace
    if "actor" in projection_ns:
        actor_ns = {
            "id": payload.get("actor_id"),
            "name": payload.get("actor_name"),
        }
        if "actor" in enrichment_ns:
            actor_id = payload.get("actor_id")
            if actor_id and actor_id != 0:
                try:
                    from app.models.user import User
                    result = await db.execute(
                        select(User.role, User.unit_id).where(User.id == actor_id)
                    )
                    row = result.first()
                    if row:
                        actor_ns["role"] = row.role
                        actor_ns["unit_id"] = row.unit_id
                except Exception as e:
                    log.warning(
                        "Failed to enrich actor context: actor_id=%s error=%s",
                        actor_id, str(e),
                    )
        context["actor"] = actor_ns

    # Build lead namespace
    if "lead" in projection_ns:
        lead_ns = {
            "id": payload.get("lead_id"),
            "name": payload.get("lead_name"),
            "officer_id": payload.get("officer_id"),
        }
        if "lead" in enrichment_ns:
            lead_id = payload.get("lead_id")
            if lead_id:
                try:
                    from app.models.lead import Lead
                    result = await db.execute(
                        select(
                            Lead.source,
                            Lead.consultation_status_id,
                            Lead.pipeline_stage_id,
                            Lead.unit_id,
                            Lead.assigned_officer_id,
                        ).where(Lead.id == lead_id)
                    )
                    row = result.first()
                    if row:
                        lead_ns["source"] = row.source
                        lead_ns["consultation_status_id"] = row.consultation_status_id
                        lead_ns["stage_id"] = row.pipeline_stage_id
                        lead_ns["unit_id"] = row.unit_id
                        lead_ns["officer_id"] = row.assigned_officer_id
                except Exception as e:
                    log.warning(
                        "Failed to enrich lead context: lead_id=%s error=%s",
                        lead_id, str(e),
                    )
        context["lead"] = lead_ns

    # Build consultation namespace
    if "consultation" in projection_ns:
        consultation_ns = {
            "id": payload.get("consultation_id"),
        }
        if "consultation" in enrichment_ns:
            consultation_id = payload.get("consultation_id")
            if consultation_id:
                try:
                    from app.models.lead import Consultation
                    result = await db.execute(
                        select(Consultation.consultation_status_id).where(
                            Consultation.id == consultation_id
                        )
                    )
                    row = result.first()
                    if row:
                        consultation_ns["status_id"] = row.consultation_status_id
                except Exception as e:
                    log.warning(
                        "Failed to enrich consultation context: consultation_id=%s error=%s",
                        consultation_id, str(e),
                    )
        context["consultation"] = consultation_ns

    return context
