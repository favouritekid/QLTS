"""Backfill ``Fee.resolved_*`` (academic_info / major / degree) snapshot.

One-time script: iterates every admission_profile that owns at least one Fee
and calls the SAME ``resnapshot_fee_academic_info_for_profile`` helper used by
calculate_fee / the decision hooks. Fail-soft: a profile whose ngành can't be
resolved (multi-NV not-yet-admitted / 0 / ≥2 admitted, or missing config) leaves
its fees' snapshot NULL — never guessed. Idempotent → safe to re-run.

Commits per batch (stream log + checkpoint) so a long run on prod can be
resumed by re-invoking (already-snapshotted profiles just resolve again).

Usage (inside backend container):
    docker compose exec -T backend \\
        python -m app.scripts.backfill_fee_resolved_major
    # prod:
    docker compose --env-file .env.production exec -T backend \\
        python -m app.scripts.backfill_fee_resolved_major
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.finance import Fee
from app.services.fee_calculation_service import (
    resnapshot_fee_academic_info_for_profile,
)

log = structlog.get_logger(__name__)


async def main(batch_size: int = 200) -> None:
    total_profiles = 0
    total_fees_updated = 0
    total_resolved_profiles = 0
    total_null_profiles = 0

    async with AsyncSessionLocal() as session:
        # Distinct profile ids owning a Fee, ordered for stable pagination.
        profile_ids = [
            row[0]
            for row in (
                await session.execute(
                    select(Fee.admission_profile_id)
                    .distinct()
                    .order_by(Fee.admission_profile_id.asc())
                )
            ).all()
        ]
        log.info("backfill_fee_resolved_major_start", profiles=len(profile_ids))

        for idx, pid in enumerate(profile_ids, 1):
            try:
                n = await resnapshot_fee_academic_info_for_profile(session, pid)
            except Exception as exc:  # defensive — never abort the whole run
                log.error(
                    "backfill_profile_failed", profile_id=pid, error=str(exc)
                )
                await session.rollback()
                continue
            total_profiles += 1
            total_fees_updated += n
            # Did this profile resolve to a major? Peek one fee.
            sample = (
                await session.execute(
                    select(Fee.resolved_major_id)
                    .where(Fee.admission_profile_id == pid)
                    .limit(1)
                )
            ).scalar()
            if sample is not None:
                total_resolved_profiles += 1
            else:
                total_null_profiles += 1

            if idx % batch_size == 0:
                await session.commit()
                log.info(
                    "backfill_checkpoint",
                    done=idx,
                    total=len(profile_ids),
                    fees_updated=total_fees_updated,
                )

        await session.commit()

        # Final audit: how many fees still NULL (expected for unresolved ngành).
        null_fees = (
            await session.execute(
                select(func.count())
                .select_from(Fee)
                .where(Fee.resolved_major_id.is_(None))
            )
        ).scalar()
        total_fees = (
            await session.execute(select(func.count()).select_from(Fee))
        ).scalar()

    log.info(
        "backfill_fee_resolved_major_done",
        profiles_processed=total_profiles,
        fees_updated=total_fees_updated,
        profiles_resolved=total_resolved_profiles,
        profiles_null=total_null_profiles,
        fees_total=total_fees,
        fees_still_null=null_fees,
    )
    print(
        f"DONE: {total_profiles} profiles · {total_fees_updated} fees updated · "
        f"resolved={total_resolved_profiles} null={total_null_profiles} · "
        f"fees_total={total_fees} fees_null={null_fees}"
    )


if __name__ == "__main__":
    asyncio.run(main())
