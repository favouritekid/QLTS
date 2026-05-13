# app/services/admission_backfill_service.py
"""Service layer for admin backfill exception queue (Q-P3-09).

Phase 3 PR-3D-B BE-2 — consumes ``_admission_backfill_exceptions`` table
created by Phase 1 #07b backfill scripts. Admin UI lists open exceptions,
optionally filters by ``exception_type`` + resolution status + date range,
and resolves rows one-at-a-time or in bulk.

V3.0 contract: mutation functions return ``(result, post_commit_callback)``;
read functions return data directly. Router commits + awaits callback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AdmissionBackfillException
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError


async def _noop_callback() -> None:
    return None


# ============================================================
# READ
# ============================================================


async def list_backfill_exceptions(
    db: AsyncSession,
    *,
    exception_type: Optional[str] = None,
    is_resolved: Optional[bool] = None,
    profile_id: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AdmissionBackfillException], int]:
    """Paginated list with admin filters.

    Returns ``(rows, total_count)``. Filters compose with AND.

    Args:
        exception_type: exact match on tag column.
        is_resolved: True → resolved_at NOT NULL; False → resolved_at IS NULL.
        profile_id: exact profile FK.
        created_from / created_to: closed-open range on created_at.
        limit: max rows to return (admin queue paginates).
        offset: skip rows for pagination.
    """
    conditions = []
    if exception_type is not None:
        conditions.append(AdmissionBackfillException.exception_type == exception_type)
    if is_resolved is True:
        conditions.append(AdmissionBackfillException.resolved_at.is_not(None))
    elif is_resolved is False:
        conditions.append(AdmissionBackfillException.resolved_at.is_(None))
    if profile_id is not None:
        conditions.append(AdmissionBackfillException.profile_id == profile_id)
    if created_from is not None:
        conditions.append(AdmissionBackfillException.created_at >= created_from)
    if created_to is not None:
        conditions.append(AdmissionBackfillException.created_at < created_to)

    where_clause = and_(*conditions) if conditions else None

    # Count query (cheap when WHERE narrows)
    count_stmt = select(func.count(AdmissionBackfillException.id))
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Data query — newest first per admin queue UX
    data_stmt = (
        select(AdmissionBackfillException)
        .order_by(AdmissionBackfillException.created_at.desc())
        .offset(offset)
        .limit(limit)
        .options(selectinload(AdmissionBackfillException.resolved_by))
    )
    if where_clause is not None:
        data_stmt = data_stmt.where(where_clause)

    rows = list((await db.execute(data_stmt)).scalars().all())
    return rows, int(total)


# ============================================================
# WRITE
# ============================================================


async def resolve_exception(
    db: AsyncSession,
    *,
    exception: AdmissionBackfillException,
    resolution_notes: str,
    actor_id: int,
) -> Tuple[AdmissionBackfillException, Callable]:
    """Mark a single exception as resolved.

    **Prechecks**:
    - resolution_notes min 5 chars (defensive — schema also enforces)
    - exception.resolved_at IS NULL (idempotent reject if already resolved)
    """
    if exception.resolved_at is not None:
        raise BusinessRuleViolation(
            f"Backfill exception {exception.id} đã được xử lý lúc "
            f"{exception.resolved_at.isoformat()}."
        )
    if not resolution_notes or len(resolution_notes.strip()) < 5:
        raise BusinessRuleViolation(
            "Resolution notes tối thiểu 5 ký tự."
        )

    exception.resolved_at = datetime.now(timezone.utc)
    exception.resolved_by_user_id = actor_id
    exception.resolution_notes = resolution_notes.strip()
    await db.flush()

    return exception, _noop_callback


async def bulk_resolve_exceptions(
    db: AsyncSession,
    *,
    exception_ids: list[int],
    resolution_notes: str,
    actor_id: int,
) -> Tuple[dict, Callable]:
    """Resolve N exceptions atomically with shared notes.

    Returns counters for admin UI feedback:
    ``{"requested": N, "resolved": K, "skipped_already_resolved": A, "missing": M}``.

    Operation is wrapped in a single transaction by the caller (router
    commits); a SQL error rolls back the whole batch.
    """
    if not exception_ids:
        raise BusinessRuleViolation("exception_ids không được trống.")
    if len(exception_ids) > 500:
        # Defensive cap — admin UI batches client-side; >500 in a single
        # PATCH suggests a misuse or runaway script.
        raise BusinessRuleViolation(
            "Tối đa 500 exception/lần. Chia nhỏ batch."
        )
    if not resolution_notes or len(resolution_notes.strip()) < 5:
        raise BusinessRuleViolation(
            "Resolution notes tối thiểu 5 ký tự."
        )

    cleaned_notes = resolution_notes.strip()
    now = datetime.now(timezone.utc)

    # Pre-fetch existing rows in one query for accurate counters
    stmt = select(AdmissionBackfillException).where(
        AdmissionBackfillException.id.in_(exception_ids)
    )
    fetched = list((await db.execute(stmt)).scalars().all())
    fetched_ids = {ex.id for ex in fetched}
    missing = set(exception_ids) - fetched_ids

    resolved = 0
    skipped_already_resolved = 0
    for ex in fetched:
        if ex.resolved_at is not None:
            skipped_already_resolved += 1
            continue
        ex.resolved_at = now
        ex.resolved_by_user_id = actor_id
        ex.resolution_notes = cleaned_notes
        resolved += 1

    await db.flush()

    counters = {
        "requested": len(exception_ids),
        "resolved": resolved,
        "skipped_already_resolved": skipped_already_resolved,
        "missing": len(missing),
        "missing_ids": sorted(missing),
    }
    return counters, _noop_callback


# ============================================================
# EXPORT
# ============================================================


async def iter_csv_rows(
    db: AsyncSession,
    *,
    exception_type: Optional[str] = None,
    is_resolved: Optional[bool] = None,
):
    """Stream-friendly iterator over filtered exceptions for CSV export.

    Yields dict rows ready for csv.DictWriter. Header columns are stable
    so admin tooling can rely on them.
    """
    conditions = []
    if exception_type is not None:
        conditions.append(AdmissionBackfillException.exception_type == exception_type)
    if is_resolved is True:
        conditions.append(AdmissionBackfillException.resolved_at.is_not(None))
    elif is_resolved is False:
        conditions.append(AdmissionBackfillException.resolved_at.is_(None))
    where_clause = and_(*conditions) if conditions else None

    stmt = (
        select(AdmissionBackfillException)
        .order_by(AdmissionBackfillException.created_at.asc())
        .options(selectinload(AdmissionBackfillException.resolved_by))
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)

    rows = (await db.execute(stmt)).scalars().all()
    for ex in rows:
        yield {
            "id": ex.id,
            "profile_id": ex.profile_id,
            "exception_type": ex.exception_type,
            "details": ex.details,
            "created_at": ex.created_at.isoformat() if ex.created_at else "",
            "resolved_at": ex.resolved_at.isoformat() if ex.resolved_at else "",
            "resolved_by_user_id": ex.resolved_by_user_id or "",
            "resolved_by_username": (
                ex.resolved_by.username if ex.resolved_by else ""
            ),
            "resolution_notes": ex.resolution_notes or "",
        }
