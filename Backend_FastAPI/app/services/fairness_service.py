# app/services/fairness_service.py
"""
Fairness Analytics Service — Phase P2-1

Analyzes assignment_decision_log to compute fairness metrics:
- Assignment distribution per officer (% share)
- Average utilization per officer
- Reason breakdown
- Fairness score (Coefficient of Variation — lower = more fair)

Read-only service — does NOT commit.
"""
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import AssignmentDecisionLog

log = structlog.get_logger(__name__)

# Minimum decisions needed for meaningful fairness analysis
MIN_DECISIONS_FOR_FAIRNESS = 10


async def get_fairness_analytics(
    db: AsyncSession,
    unit_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Analyze assignment_decision_log for fairness metrics.

    Args:
        unit_id: Filter by unit (None = all units, for admin)
        date_from: Start of analysis window
        date_to: End of analysis window

    Returns:
        Dict with summary, officer_distribution, reason_breakdown, fairness_score
    """
    filters: list = []
    if unit_id is not None:
        filters.append(AssignmentDecisionLog.unit_id == unit_id)
    if date_from is not None:
        filters.append(AssignmentDecisionLog.decision_at >= date_from)
    if date_to is not None:
        filters.append(AssignmentDecisionLog.decision_at < date_to)

    # --- Summary ---
    summary_q = select(
        func.count(AssignmentDecisionLog.id).label("total"),
        func.count(AssignmentDecisionLog.assigned_officer_id).label("successful"),
        func.count(
            case((AssignmentDecisionLog.assigned_officer_id.is_(None), 1))
        ).label("failed"),
    )
    if filters:
        summary_q = summary_q.where(*filters)
    summary_row = (await db.execute(summary_q)).one()
    total = summary_row.total
    successful = summary_row.successful
    failed = summary_row.failed

    if total == 0:
        return {
            "summary": {"total_decisions": 0, "successful": 0, "failed": 0},
            "officer_distribution": [],
            "reason_breakdown": [],
            "fairness_score": None,
            "fairness_label": "insufficient_data",
            "warning": "Chưa có dữ liệu assignment decision log",
        }

    # --- Officer distribution (% share of successful assignments) ---
    dist_q = (
        select(
            AssignmentDecisionLog.assigned_officer_id,
            func.count(AssignmentDecisionLog.id).label("count"),
        )
        .where(AssignmentDecisionLog.assigned_officer_id.isnot(None))
        .group_by(AssignmentDecisionLog.assigned_officer_id)
        .order_by(func.count(AssignmentDecisionLog.id).desc())
    )
    if filters:
        dist_q = dist_q.where(*filters)
    dist_rows = (await db.execute(dist_q)).all()

    officer_distribution = []
    assignment_counts: List[int] = []
    for row in dist_rows:
        share = round(row.count / successful * 100, 1) if successful > 0 else 0
        officer_distribution.append({
            "officer_id": row.assigned_officer_id,
            "assignments": row.count,
            "share_pct": share,
        })
        assignment_counts.append(row.count)

    # --- Average utilization per officer (from capacity_snapshot) ---
    cap_q = (
        select(
            AssignmentDecisionLog.assigned_officer_id,
            AssignmentDecisionLog.capacity_snapshot,
        )
        .where(
            AssignmentDecisionLog.assigned_officer_id.isnot(None),
            AssignmentDecisionLog.capacity_snapshot.isnot(None),
        )
    )
    if filters:
        cap_q = cap_q.where(*filters)
    cap_rows = (await db.execute(cap_q)).all()

    # Aggregate utilization per officer
    util_accum: Dict[int, List[float]] = {}
    for row in cap_rows:
        oid = row.assigned_officer_id
        snap = row.capacity_snapshot or {}
        officer_key = str(oid)
        if officer_key in snap:
            entry = snap[officer_key]
            if isinstance(entry, dict) and entry.get("max", 0) > 0:
                util_accum.setdefault(oid, []).append(
                    entry.get("current", 0) / entry["max"]
                )

    for item in officer_distribution:
        oid = item["officer_id"]
        utils = util_accum.get(oid, [])
        item["avg_utilization"] = round(sum(utils) / len(utils), 3) if utils else None

    # --- Reason breakdown ---
    reason_q = (
        select(
            AssignmentDecisionLog.reason,
            func.count(AssignmentDecisionLog.id).label("count"),
        )
        .group_by(AssignmentDecisionLog.reason)
        .order_by(func.count(AssignmentDecisionLog.id).desc())
    )
    if filters:
        reason_q = reason_q.where(*filters)
    reason_rows = (await db.execute(reason_q)).all()

    reason_breakdown = [
        {"reason": row.reason or "unknown", "count": row.count,
         "pct": round(row.count / total * 100, 1)}
        for row in reason_rows
    ]

    # --- Fairness score (Coefficient of Variation) ---
    # CV = std_dev / mean — lower = more equal distribution
    # 0 = perfectly equal, >0.5 = highly unequal
    fairness_score = None
    fairness_label = "insufficient_data"
    warning = None

    if total < MIN_DECISIONS_FOR_FAIRNESS:
        warning = f"Cần tối thiểu {MIN_DECISIONS_FOR_FAIRNESS} quyết định để tính fairness (hiện có {total})"
    elif len(assignment_counts) >= 2:
        mean = sum(assignment_counts) / len(assignment_counts)
        if mean > 0:
            variance = sum((c - mean) ** 2 for c in assignment_counts) / len(assignment_counts)
            std_dev = math.sqrt(variance)
            fairness_score = round(std_dev / mean, 3)

            if fairness_score <= 0.15:
                fairness_label = "excellent"
            elif fairness_score <= 0.3:
                fairness_label = "good"
            elif fairness_score <= 0.5:
                fairness_label = "moderate"
            else:
                fairness_label = "poor"
    elif len(assignment_counts) == 1:
        fairness_score = 0.0
        fairness_label = "single_officer"
        warning = "Chỉ có 1 officer nhận assignment — không thể đánh giá phân bổ"

    return {
        "summary": {
            "total_decisions": total,
            "successful": successful,
            "failed": failed,
        },
        "officer_distribution": officer_distribution,
        "reason_breakdown": reason_breakdown,
        "fairness_score": fairness_score,
        "fairness_label": fairness_label,
        "warning": warning,
    }
