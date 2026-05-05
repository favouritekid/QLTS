"""Wave 3-E / M-1-15a — DROP UNIQUE(lead_id) → ADD UNIQUE(lead_id, academic_year) ⚠ ONE-WAY.

Final ⚠ ONE-WAY migration of Wave 3 — completes Phase 1 Schema 100%
post-merge. Removes the legacy single-profile-per-lead constraint and
replaces it with a composite ``(lead_id, academic_year)`` UNIQUE so a
lead can apply for multiple academic years (one profile per year per
lead) per PLAN line 3312-3346.

Live DB naming convention (verified ``\\d admission_profile`` 2026-05-05)
-----------------------------------------------------------------------

The legacy UNIQUE constraint was created from ``unique=True +
index=True`` on ``AdmissionProfile.lead_id``. SQLAlchemy emits this as
ONE UNIQUE INDEX named ``ix_admission_profile_lead_id`` (``ix_*``
prefix), NOT a separate ``_lead_id_key`` constraint. Verified live;
migration uses the live name. Same correction pattern as Wave 3-D
phase1_18 (PR #222 squash 958435cf).

3-step DDL
----------

1. DROP legacy UNIQUE INDEX ``ix_admission_profile_lead_id`` —
   removes the single-profile-per-lead enforcement.
2. CREATE non-unique INDEX ``ix_admission_profile_lead_id`` ON
   ``(lead_id)`` — preserves FK lookup performance. Same name reused
   intentionally; the index transitions from UNIQUE to plain.
3. ADD UNIQUE CONSTRAINT ``uq_admission_profile_lead_year`` ON
   ``(lead_id, academic_year)`` — preserves business invariant: 1
   lead → 1 profile / academic year.

ONE-WAY downgrade contract
--------------------------

After this migration ships, the application (Wave 4 PR #15b) will
flip ``Lead.admission_profile`` from singular ``uselist=False`` to
plural ``admission_profiles`` and start letting leads accumulate
profiles across years. Reverting requires:
* application rolling back to single-profile-per-lead semantics, AND
* DB having no lead with >1 profile.

If any lead has >1 profile (post-Wave-4 multi-year data), recreating
the legacy single UNIQUE on ``lead_id`` would FAIL at the ``CREATE``
step. Defensive guard counts pre-existing offenders BEFORE drop —
raises ``RuntimeError`` with snapshot-restore hint.

Coupled deliverables in this PR
-------------------------------

* ``app/models/admission.py:44-58`` — ``AdmissionProfile.__table_args__``
  carries the new composite UNIQUE so test DB
  (``Base.metadata.create_all()``) stays in sync. Memory
  ``test-db-schema-source`` flagged drift symptom previously; same-
  commit update prevents.
* ``lead_id`` column ``unique=True`` removed; relationship stays
  singular (``uselist=False``) — flip to plural ships in Wave 4 PR
  #15b paired with model + repository + service updates per PLAN
  line 3320-3331. Wave 3-E is DDL-only; the application contract
  remains 1-profile-per-lead until Wave 4.

Live cold cutover rehearsal (dev DB w/ prod data 2026-05-05)
------------------------------------------------------------

Pre-flight verified live:
* 9 admission_profile rows in dev DB (post prod-data import).
* 0 lead_id duplicates: ``GROUP BY lead_id HAVING COUNT(*) > 1``
  returns 0 rows.
* 0 (lead_id, academic_year) duplicates: same query with composite
  GROUP BY returns 0 rows.

Zero conflict risk for both the UNIQUE swap and the defensive
downgrade rebuild — every existing row satisfies both constraints.

Solo cold cutover semantics — no inter-PR soak window
-----------------------------------------------------

PLAN line 3468-3473 specs a 1-week soak between phase1_15a (DDL drop)
/ phase1_15b (model+service plural) / phase1_15c (FE migrate). Per
memory ``solo-cutover-simple-data-import`` 2026-05-05 pivot, solo
cold cutover ships the entire branch in 1 maintenance window — soak
windows are team-style staged rollout semantic that doesn't apply
when there's no concurrent traffic during the swap. Wave 4 PRs #15b
+ #15c ship sequentially without soak.

Revision ID: phase1_15a
Revises: phase1_18
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "phase1_15a"
down_revision: Union[str, None] = "phase1_18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "admission_profile"

# Live DB naming convention — SQLAlchemy ``unique=True + index=True``
# on the lead_id column produces ONE UNIQUE INDEX with the ``ix_*``
# prefix. Verified via ``\d admission_profile`` 2026-05-05.
LEAD_ID_INDEX = "ix_admission_profile_lead_id"

# New composite UNIQUE — 1 profile per (lead, academic_year).
COMPOSITE_UNIQUE_NAME = "uq_admission_profile_lead_year"


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _is_index_unique(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    for idx in inspector.get_indexes(table_name):
        if idx["name"] == index_name:
            return bool(idx.get("unique", False))
    return False


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    for c in inspector.get_unique_constraints(table_name):
        if c["name"] == constraint_name:
            return True
    return False


def upgrade() -> None:
    """3-step UNIQUE swap.

    Idempotency: each step inspects current state before executing.
    Safe to re-run if half-applied state.
    """
    # Step 1: DROP legacy UNIQUE INDEX (only if it's still UNIQUE —
    # if a prior run already converted it to plain, skip).
    if _index_exists(TABLE, LEAD_ID_INDEX) and _is_index_unique(TABLE, LEAD_ID_INDEX):
        op.drop_index(LEAD_ID_INDEX, table_name=TABLE)

    # Step 2: RECREATE as plain (non-unique) index for FK lookup
    # performance. Same name reused; the index transitions
    # UNIQUE → plain.
    if not _index_exists(TABLE, LEAD_ID_INDEX):
        op.create_index(LEAD_ID_INDEX, TABLE, ["lead_id"])

    # Step 3: ADD composite UNIQUE — 1 profile / lead / academic_year.
    if not _constraint_exists(TABLE, COMPOSITE_UNIQUE_NAME):
        op.create_unique_constraint(
            COMPOSITE_UNIQUE_NAME,
            TABLE,
            ["lead_id", "academic_year"],
        )


def downgrade() -> None:
    """⚠ ONE-WAY — defensive guard against multi-year-per-lead rows.

    If any lead has >1 profile, recreating the legacy single UNIQUE
    on ``lead_id`` would fail at CREATE (multiple rows violate the
    new constraint). Surface the violation up-front instead of
    failing mid-DDL.
    """
    bind = op.get_bind()
    multi_profile_leads = bind.execute(
        sa.text(
            f"""
            SELECT COUNT(*) FROM (
                SELECT lead_id FROM {TABLE}
                GROUP BY lead_id
                HAVING COUNT(*) > 1
            ) AS multi
            """
        )
    ).scalar()
    if multi_profile_leads and multi_profile_leads > 0:
        raise RuntimeError(
            f"Cannot downgrade phase1_15a: {multi_profile_leads} lead(s) in "
            f"{TABLE} hold >1 profile (multi-year semantics already in "
            f"flight). This is a ONE-WAY migration — restore from a "
            f"pre-Wave-3 snapshot instead of running `alembic downgrade`. "
            f"Manual cleanup playbook: collapse multi-year profiles per "
            f"lead before re-running this downgrade."
        )

    # Reverse order: drop composite UNIQUE, recreate legacy UNIQUE
    # INDEX on lead_id.
    if _constraint_exists(TABLE, COMPOSITE_UNIQUE_NAME):
        op.drop_constraint(COMPOSITE_UNIQUE_NAME, TABLE, type_="unique")

    if _index_exists(TABLE, LEAD_ID_INDEX) and not _is_index_unique(TABLE, LEAD_ID_INDEX):
        op.drop_index(LEAD_ID_INDEX, table_name=TABLE)

    if not _index_exists(TABLE, LEAD_ID_INDEX):
        op.create_index(LEAD_ID_INDEX, TABLE, ["lead_id"], unique=True)
