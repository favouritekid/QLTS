"""One-shot backfill: revert leads wrongly at sts10 "Đã hoàn tất học phí".

Companion to the PR-1 code change (``is_hk1_cleared`` → ``is_hk1_settled``):
before the fix, the FIRST partial HK1 tuition payment projected the lead to
sts10 "Đã hoàn tất học phí" even though the fee still had a balance. Prod audit
2026-06-27 found 79/83 sts10 leads in this state (~399tr hidden unpaid HK1).

This script reverts those leads to the status they held BEFORE the (wrong)
sts10 projection — symmetric to the runtime void path. It REUSES
``revert_lead_tuition_paid`` so the restore logic + guards are byte-identical to
production code:

  * Guard: only acts on a lead CURRENTLY at sts10 (a lead that legitimately
    advanced afterwards — e.g. manual fix, SLA close — is skipped, never
    overwritten).
  * Restore: reads the most-recent ``LeadStatusHistory`` row that pushed the
    lead INTO sts10 and restores its ``old_*`` verbatim (no hardcoded target,
    no re-derive). For these leads that pre-state is sts14 "Chưa hoàn tất học
    phí".
  * The new audit row is written with ``changed_by_user_id = NULL`` (system).

Idempotent: a re-run matches zero rows because reverted leads are no longer at
sts10. Anomalies (no forward history, or a history row with NULL
old_consultation_status_id) are ISOLATED and reported — NEVER restored blindly.

⚠️ DEPLOY ORDER: run this ONLY AFTER the PR-1 code is live, otherwise the old
forward logic will re-mislabel a lead right after it is reverted.

Usage:
    python scripts/backfill_sts10_partial_to_sts14.py            # DRY-RUN
    python scripts/backfill_sts10_partial_to_sts14.py --apply    # revert (prompts)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app import models  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.services.lead_admission_sync import (  # noqa: E402
    TUITION_PAID_STATUS,
    revert_lead_tuition_paid,
)

# Leads at sts10 whose HK1 tuition fee still has a positive balance (remaining
# > 0) — i.e. NOT actually fully settled. ``profile_id`` is the profile that
# carries the offending fee; the most-recent forward history row gives the
# restore target (for reporting + the anomaly check). DISTINCT lead so a lead
# with >1 offending profile is processed once (revert is idempotent anyway).
_AFFECTED_SQL = text(
    """
    SELECT DISTINCT ON (l.id)
        l.id            AS lead_id,
        l.full_name     AS full_name,
        ap.id           AS profile_id,
        (f.final_amount - f.paid_amount - f.waived_amount) AS remaining,
        h.old_consultation_status_id AS target_cs
    FROM lead l
    JOIN admission_profile ap ON ap.lead_id = l.id
    JOIN fee f
        ON f.admission_profile_id = ap.id
       AND f.fee_type = 'tuition'
       AND f.semester_no = 1
       AND f.status <> 'cancelled'
       AND (f.final_amount - f.paid_amount - f.waived_amount) > 0
    LEFT JOIN LATERAL (
        SELECT old_consultation_status_id
        FROM lead_status_history
        WHERE lead_id = l.id
          AND new_consultation_status_id = :sts10
        ORDER BY id DESC
        LIMIT 1
    ) h ON TRUE
    WHERE l.consultation_status_id = :sts10
      -- Only revert when NO HK1 fee justifies the sts10 label: a lead with any
      -- SETTLED (non-cancelled) HK1 tuition fee genuinely "đã hoàn tất học phí"
      -- (e.g. a prior year/profile fully paid) — never strip its valid label.
      -- Cancelled fees are excluded from the offending JOIN above too, so a
      -- cancelled fee with a residual remaining>0 cannot drag a lead here.
      AND NOT EXISTS (
          SELECT 1
          FROM admission_profile ap2
          JOIN fee f2 ON f2.admission_profile_id = ap2.id
          WHERE ap2.lead_id = l.id
            AND f2.fee_type = 'tuition'
            AND f2.semester_no = 1
            AND f2.status <> 'cancelled'
            AND (f2.final_amount - f2.paid_amount - f2.waived_amount) <= 0
      )
    ORDER BY l.id
    """
)


async def select_affected(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(_AFFECTED_SQL, {"sts10": TUITION_PAID_STATUS})
    ).mappings().all()
    return [dict(r) for r in rows]


async def main() -> int:
    apply = "--apply" in sys.argv

    async with AsyncSessionLocal() as db:
        affected = await select_affected(db)
        anomalies = [r for r in affected if not r["target_cs"]]
        actionable = [r for r in affected if r["target_cs"]]

        print(f"Leads at {TUITION_PAID_STATUS} with unpaid HK1 (remaining>0): "
              f"{len(affected)}")
        print(f"  actionable (have forward history): {len(actionable)}")
        print(f"  anomalies (no/NULL forward history — SKIPPED): {len(anomalies)}")
        print()
        # Backup snapshot (printed so the run log is the rollback reference).
        print("--- affected leads (backup snapshot) ---")
        for r in affected:
            tag = "" if r["target_cs"] else "  <ANOMALY: skip>"
            print(f"  lead={r['lead_id']:>5} profile={r['profile_id']:>5} "
                  f"remaining={r['remaining']:>12} -> {r['target_cs']}{tag} "
                  f"| {r['full_name']}")
        print()

        if not apply:
            print("DRY-RUN — re-run with --apply to revert the actionable leads.")
            return 0
        if not actionable:
            print("Nothing actionable to backfill.")
            return 0

        print(f"\n⚠️  Will revert {len(actionable)} lead(s) {TUITION_PAID_STATUS} "
              f"-> pre-state (sts14). Continue? (yes/no): ", end="")
        if input().strip().lower() != "yes":
            print("Cancelled.")
            return 1

        reverted = 0
        skipped = 0
        for r in actionable:
            profile = (
                await db.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == r["profile_id"])
                    .options(selectinload(models.AdmissionProfile.lead))
                )
            ).scalar_one_or_none()
            if profile is None or profile.lead is None:
                skipped += 1
                continue
            ok = await revert_lead_tuition_paid(
                db,
                profile,
                changed_by_user_id=None,
                reason=("Backfill: sửa nhãn học phí đóng một phần "
                        f"{TUITION_PAID_STATUS}->sts14 (PR-1 is_hk1_settled)"),
            )
            if ok:
                reverted += 1
            else:
                skipped += 1
        await db.commit()

        print(f"✅ Backfill done: reverted={reverted}, skipped={skipped}, "
              f"anomalies={len(anomalies)}")

        # Verification: the actionable bucket must now be empty.
        remaining = await select_affected(db)
        still = [x for x in remaining if x["target_cs"]]
        print(f"Re-check actionable remaining (expect 0): {len(still)}")
        return 0 if not still else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
