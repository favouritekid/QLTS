"""sts20 CONSULT_GIVEUP: terminal give-up status + 2 transitions (no auto-backfill)

Revision ID: sts20_consult_giveup_20260609
Revises: finance_phase1_20260608
Create Date: 2026-06-09

Adds consultation_status sts20 (CONSULT_GIVEUP — terminal, is_final=true) plus
two sts04->sts20 transitions (system: SLA beat; role: manager/admin manual).

2-step rollout: this migration only SEEDS the status + transitions — it does NOT
backfill existing stale sts04 leads. Closing existing/stale leads is a deliberate,
observable step run later via scripts/backfill_sts20_giveup.py, and the daily
beat stays off until SLA_AUTO_GIVEUP_ENABLED=true. So deploying the migration is
non-destructive: manager/admin manual close works immediately, but no lead is
auto-closed until the operator opts in (after the reopen workflow is ready).

Idempotent (migration-predicate-safety):
- consultation_status INSERT uses ON CONFLICT (id) DO NOTHING (PK guard).
- allowed_transitions INSERT uses WHERE NOT EXISTS (the table has NO unique
  constraint on (from, to, trigger) — ON CONFLICT DO NOTHING would NOT dedupe).

downgrade() still reverts ANY lead in sts20 (closed by manual/beat/backfill)
back to sts04 — see below.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "sts20_consult_giveup_20260609"
down_revision: Union[str, None] = "finance_phase1_20260608"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. Seed consultation_status sts20 (CONSULT_GIVEUP) ---------------
    # Column order mirrors the operational-baseline seed
    # (zq6w7x8y9z0a1_seed_operational_baseline.py). description is left at the
    # DB default (NULL), like every other seeded status.
    conn.execute(text("""
        INSERT INTO consultation_status
        (id, code, name, stage_id, color_code, outcome_type, is_final, status_type,
         selectable_mode, is_universal, updates_pipeline, counts_for_funnel, phase,
         display_order, legacy_status)
        VALUES
        ('sts20', 'CONSULT_GIVEUP', 'Đã ngừng tư vấn', 'stg02', '#991B1B', 'negative',
         true, 'transition', 'role', false, true, true, 'consultation', 35, NULL)
        ON CONFLICT (id) DO NOTHING
    """))

    # --- 2. Seed the two sts04 -> sts20 transitions (idempotent) ----------
    # system: daily SLA beat auto-close. role: manager/admin manual close.
    conn.execute(text("""
        INSERT INTO allowed_transitions
        (from_status_id, to_status_id, trigger_type, required_phase, is_active, created_at, updated_at)
        SELECT 'sts04', 'sts20', 'system', 'consultation', true, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM allowed_transitions
            WHERE from_status_id='sts04' AND to_status_id='sts20' AND trigger_type='system'
        )
    """))
    conn.execute(text("""
        INSERT INTO allowed_transitions
        (from_status_id, to_status_id, trigger_type, required_phase, is_active, created_at, updated_at)
        SELECT 'sts04', 'sts20', 'role', 'consultation', true, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM allowed_transitions
            WHERE from_status_id='sts04' AND to_status_id='sts20' AND trigger_type='role'
        )
    """))
    print(
        "  [sts20] consultation_status + 2 transitions seeded. "
        "Backfill of existing stale sts04 leads is INTENTIONALLY NOT run here "
        "(2-step rollout) — run scripts/backfill_sts20_giveup.py deliberately."
    )


def downgrade() -> None:
    conn = op.get_bind()

    # WARNING: this is a DESTRUCTIVE full rollback. Because sts20 is being
    # dropped, EVERY lead in sts20 must be reverted to sts04 and ALL sts20
    # history rows deleted — there is no way to keep them once the status FK
    # target is gone. That includes give-ups the daily SLA beat performed AFTER
    # deploy (not just this migration's backfill): those leads snap back to
    # active sts04 (re-inflating officer workload) and their audit trail is
    # lost irreversibly. Do NOT downgrade once the beat has run in production.
    print(
        "  [sts20] downgrade WARNING: reverting ALL sts20 leads to sts04 and "
        "deleting ALL sts20 history (incl. post-deploy beat give-ups)."
    )

    # Order avoids FK orphans: clear lead refs -> delete history rows ->
    # delete transitions -> delete the status itself.
    #
    # 1. Return every sts20 lead to sts04 (re-engageable). status='contacted'
    #    is the canonical sts04 derivation (derive_lead_status Rule 4). This
    #    covers both backfilled and beat-moved leads.
    conn.execute(text("""
        UPDATE lead
        SET consultation_status_id = 'sts04',
            pipeline_stage_id = 'stg02',
            status = 'contacted',
            updated_at = NOW()
        WHERE consultation_status_id = 'sts20'
    """))

    # 1b. Revert any consultation rows whose outcome was a manual sts20 close
    #     (consultation.consultation_status_id FK -> consultation_status has no
    #     ON DELETE CASCADE, so this must precede the status delete). Only
    #     possible once the manual role transition is reachable; harmless no-op
    #     otherwise.
    conn.execute(text("""
        UPDATE consultation
        SET consultation_status_id = 'sts04'
        WHERE consultation_status_id = 'sts20'
    """))

    # 2. Remove sts20 history rows (FK new/old_consultation_status_id ->
    #    consultation_status has no ON DELETE CASCADE, so this must precede the
    #    status delete). sts20 is terminal so old_consultation_status_id='sts20'
    #    should never exist, but cover it defensively.
    conn.execute(text("""
        DELETE FROM lead_status_history
        WHERE new_consultation_status_id = 'sts20'
           OR old_consultation_status_id = 'sts20'
    """))

    # 3. Delete the two transitions this migration seeded (system + role only),
    #    so a pre-existing sts04->sts20 row with a different trigger_type that
    #    upgrade's WHERE-NOT-EXISTS skipped is not collaterally removed. (Also
    #    covered by to_status_id ON DELETE CASCADE, but be explicit + precise.)
    conn.execute(text("""
        DELETE FROM allowed_transitions
        WHERE from_status_id = 'sts04' AND to_status_id = 'sts20'
          AND trigger_type IN ('system', 'role')
    """))

    # 4. Drop the status.
    conn.execute(text("DELETE FROM consultation_status WHERE id = 'sts20'"))
    print("  [sts20] downgrade complete: leads reverted to sts04, status removed")
