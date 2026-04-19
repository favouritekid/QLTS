"""Backfill Zalo ``NotificationConsent`` rows for existing leads.

One-time script: iterates all non-deleted leads that have a phone and lack
a Zalo consent row, calling the same ``grant_implied_zalo_consent`` helper
as ``lead_service.create_lead``. Safe to re-run (helper is idempotent via
``upsert_latest``).

Usage (inside backend container):
    docker compose --env-file .env.production exec -T backend \\
        python -m app.scripts.backfill_implied_zalo_consent
"""
from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Lead
from app.models.notification_consent import NotificationConsent
from app.services import notification_consent_service

log = structlog.get_logger(__name__)


async def main(batch_size: int = 500) -> None:
    total_considered = 0
    total_granted = 0
    total_skipped_existing = 0
    total_skipped_no_phone = 0

    async with AsyncSessionLocal() as session:
        # Pre-fetch existing consent source_ids (zalo/lead) to skip quickly.
        existing_q = select(NotificationConsent.source_id).where(
            and_(
                NotificationConsent.channel == "zalo",
                NotificationConsent.source_type == "lead",
            )
        )
        existing_rows = (await session.execute(existing_q)).scalars().all()
        existing_set = {int(x) for x in existing_rows}
        log.info("backfill_start", existing_consent_rows=len(existing_set))

        # Paginate leads by id ASC.
        last_id = 0
        while True:
            batch = (
                await session.execute(
                    select(Lead)
                    .where(
                        and_(
                            Lead.id > last_id,
                            Lead.deleted_at.is_(None),
                        )
                    )
                    .order_by(Lead.id.asc())
                    .limit(batch_size)
                )
            ).scalars().all()
            if not batch:
                break

            for lead in batch:
                last_id = lead.id
                total_considered += 1
                if lead.id in existing_set:
                    total_skipped_existing += 1
                    continue
                if not lead.phone:
                    total_skipped_no_phone += 1
                    continue
                await notification_consent_service.grant_implied_zalo_consent(
                    session, lead, actor_id=None,
                )
                total_granted += 1

            await session.commit()
            log.info(
                "backfill_batch_committed",
                last_id=last_id,
                considered=total_considered,
                granted=total_granted,
            )

    log.info(
        "backfill_done",
        considered=total_considered,
        granted=total_granted,
        skipped_existing=total_skipped_existing,
        skipped_no_phone=total_skipped_no_phone,
    )
    print(
        f"considered={total_considered} granted={total_granted} "
        f"skipped_existing={total_skipped_existing} "
        f"skipped_no_phone={total_skipped_no_phone}"
    )


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
