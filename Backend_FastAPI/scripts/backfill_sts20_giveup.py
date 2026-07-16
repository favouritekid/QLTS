"""
One-shot backfill: close existing stale sts04 leads -> sts20 (CONSULT_GIVEUP).

2-step-rollout companion to migration ``sts20_consult_giveup_20260609`` (which
only SEEDS the status + transitions). The migration is intentionally
non-destructive; run THIS script deliberately — once the reopen workflow /
observation window is ready — to close existing stale rejections.

Predicate matches the daily beat exactly: consultation_status_id='sts04',
deleted_at IS NULL, COALESCE(GREATEST(consultation_reengaged_at,
last_consultation_at), updated_at, created_at) older than
SLA_CONSULT_GIVEUP_DAYS. Idempotent: a re-run matches zero rows because
moved leads are no longer in sts04.

Phải giữ ĐỒNG BỘ với ``sla_tasks._stale_predicate`` — lệch nhau thì dry-run
đếm một tập, beat đóng một tập khác.

Usage:
    python scripts/backfill_sts20_giveup.py            # DRY-RUN (count only)
    python scripts/backfill_sts20_giveup.py --apply    # actually close (prompts)
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402

# Strict SLA predicate (same rows as the runtime beat). :days bound at call time.
# GREATEST (không phải COALESCE) giữa mốc re-engage thủ công và recency tư vấn —
# xem giải thích đầy đủ ở ``sla_tasks._stale_predicate``. Hai nơi PHẢI khớp nhau.
_STALE_STS04_PREDICATE = (
    "consultation_status_id = 'sts04' "
    "AND deleted_at IS NULL "
    "AND COALESCE("
    "      GREATEST(consultation_reengaged_at, last_consultation_at), "
    "      updated_at, created_at) "
    "    < NOW() - (:days * INTERVAL '1 day')"
)


async def count_stale_sts04(db: AsyncSession, days: int) -> int:
    """Count leads the backfill would close (dry-run)."""
    result = await db.execute(
        text(f"SELECT count(*) FROM lead WHERE {_STALE_STS04_PREDICATE}"),
        {"days": days},
    )
    return result.scalar() or 0


async def backfill_stale_sts04(db: AsyncSession, days: int) -> dict:
    """Close stale sts04 leads -> sts20 via the SAME code path as the daily beat
    (close_stale_rejected_leads). So status is derived by sync_lead_status (no
    hardcoded 'rejected' duplicating derive_lead_status), idempotency (RULE #13)
    + FOR UPDATE SKIP LOCKED apply, and reason_tag='backfill_sla_auto_giveup'
    keeps backfill rows distinguishable from the daily beat's in audit.
    Commits internally (per batch). Returns {checked, transitioned, skipped, errors}.
    """
    from app.tasks.sla_tasks import close_stale_rejected_leads  # noqa: E402

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return await close_stale_rejected_leads(
        db, cutoff=cutoff, days=days, reason_tag="backfill_sla_auto_giveup",
    )


async def main() -> int:
    apply = "--apply" in sys.argv
    days = settings.SLA_CONSULT_GIVEUP_DAYS

    async with AsyncSessionLocal() as db:
        # Guard: the migration must have seeded sts20 first.
        exists = (await db.execute(
            text("SELECT 1 FROM consultation_status WHERE id = 'sts20'")
        )).scalar()
        if not exists:
            print("❌ sts20 not found — run 'alembic upgrade head' first.")
            return 1

        # Guard: the predicate reads consultation_reengaged_at, added by a LATER
        # revision (leadreopen_a_20260609) than the one seeding sts20. Standing
        # at the sts20 revision — the runbook's "downgrade -1" rollback point —
        # the query would die with an opaque UndefinedColumn instead of this.
        has_col = (await db.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'lead' AND column_name = 'consultation_reengaged_at'"
        ))).scalar()
        if not has_col:
            print(
                "❌ lead.consultation_reengaged_at not found — run "
                "'alembic upgrade head' first (revision leadreopen_a_20260609)."
            )
            return 1

        n = await count_stale_sts04(db, days)
        print(f"Stale sts04 leads (≥ {days} days): {n}")

        if not apply:
            print("DRY-RUN — re-run with --apply to close them.")
            return 0
        if n == 0:
            print("Nothing to backfill.")
            return 0

        print(
            f"\n⚠️  Will close {n} lead(s) to sts20 (TERMINAL — reopen requires "
            f"the lead-reopen workflow). Continue? (yes/no): ",
            end="",
        )
        if input().strip().lower() != "yes":
            print("Cancelled.")
            return 1

        # close_stale_rejected_leads commits per batch internally.
        res = await backfill_stale_sts04(db, days)
        print(
            f"✅ Backfill done: transitioned={res['transitioned']}, "
            f"skipped={res['skipped']}, errors={res['errors']}"
        )
        return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
