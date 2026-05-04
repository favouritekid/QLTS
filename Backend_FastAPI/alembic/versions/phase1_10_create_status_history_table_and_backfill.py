"""phase1_10: create admission_profile_status_history + backfill

Revision ID: phase1_10
Revises: phase1_09a
Create Date: 2026-05-04

#184 Wave 2 PR-2A second migration. Create the status history
audit table per PLAN Phần 2.7 + backfill 1 row/profile (initial
state) + 5 scattered scalar audit migrate blocks (approved,
rejected, revision_requested, resubmitted, overridden).

PLAN refs
---------
* §4 P1 #10 (line 2973-3039) — table create + 6 backfill blocks.
* §2.7 (line 1018-1069) — table schema + CHECK constraint.
* P1 fix #1 (line 182) + P1 fix #2 (line 201) — 3-column role
  audit (deprecated transitioned_by_role + new actor_actual_role
  + new effective_transition_role).
* P2 fix #6 (line 409) — actor model split user_id + lead_id.

Schema
------

* ``admission_profile_status_history``:
  - ``id`` SERIAL PK
  - ``profile_id`` integer FK → ``admission_profile(id)`` ON
    DELETE CASCADE
  - ``from_status`` varchar(20) nullable (NULL = profile creation)
  - ``to_status`` varchar(20) NOT NULL
  - ``transitioned_by_user_id`` integer FK → ``user(id)`` nullable
  - ``transitioned_by_lead_id`` integer FK → ``lead(id)`` nullable
  - ``transitioned_by_role`` ``transition_role_legacy`` ENUM
    NOT NULL (deprecated 1 release; will drop Phase 4)
  - ``actor_actual_role`` ``actor_actual_role`` ENUM NOT NULL
  - ``effective_transition_role`` ``effective_transition_role``
    ENUM NOT NULL
  - ``transition_reason`` text nullable
  - ``occurred_at`` timestamptz NOT NULL DEFAULT now()
  - ``metadata`` JSONB nullable (default '{}')

* Indexes:
  - ``ix_status_history_profile_occurred`` (profile_id, occurred_at DESC)
  - ``ix_status_history_to_status`` (to_status)

* CHECK ``ck_status_history_actor_consistency``: per PLAN line 1058-1064.

ENUM types
----------
Three ENUMs needed:

* ``transition_role_legacy`` (4 values, deprecated): ``system``,
  ``officer``, ``admin``, ``candidate``. Old column.
* ``actor_actual_role`` (6 values): ``candidate``, ``officer``,
  ``manager``, ``accountant``, ``admin``, ``system``.
* ``effective_transition_role`` (4 values): ``candidate``,
  ``officer``, ``admin``, ``system``.

Backfill
--------
6 blocks per PLAN line 2975-3038:

1. Initial state — 1 row/profile with from_status=NULL,
   to_status=current. Idempotent: WHERE NOT EXISTS.
2. Approved transitions — from scattered ``approved_at/by``.
3. Rejected — from ``rejected_at/by``.
4. Revision requested — from ``revision_requested_at/by``.
5. Resubmitted — from ``resubmitted_at/by``.
6. Overridden — from ``overridden_at/by``.

Each scattered scalar block: idempotent via NOT EXISTS check on
metadata.source = 'scattered_scalar_backfill' for the same
(profile, transition).

Down-revision chain: ``phase1_09a → phase1_10``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_10"
down_revision: Union[str, None] = "phase1_09a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ENUM definitions (PLAN line 1032-1043 + role-actor consistency).
TRANSITION_ROLE_LEGACY_VALUES: tuple[str, ...] = (
    "system", "officer", "admin", "candidate",
)
ACTOR_ACTUAL_ROLE_VALUES: tuple[str, ...] = (
    "candidate", "officer", "manager", "accountant", "admin", "system",
)
EFFECTIVE_TRANSITION_ROLE_VALUES: tuple[str, ...] = (
    "candidate", "officer", "admin", "system",
)


def upgrade() -> None:
    # 1. Create 3 ENUM types BEFORE table.
    legacy_enum = postgresql.ENUM(
        *TRANSITION_ROLE_LEGACY_VALUES,
        name="transition_role_legacy",
        create_type=False,
    )
    legacy_enum.create(op.get_bind(), checkfirst=True)

    actor_actual_enum = postgresql.ENUM(
        *ACTOR_ACTUAL_ROLE_VALUES,
        name="actor_actual_role",
        create_type=False,
    )
    actor_actual_enum.create(op.get_bind(), checkfirst=True)

    effective_enum = postgresql.ENUM(
        *EFFECTIVE_TRANSITION_ROLE_VALUES,
        name="effective_transition_role",
        create_type=False,
    )
    effective_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create table per PLAN Phần 2.7.
    op.create_table(
        "admission_profile_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("admission_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column(
            "transitioned_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "transitioned_by_lead_id",
            sa.Integer(),
            sa.ForeignKey("lead.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("transitioned_by_role", legacy_enum, nullable=False),
        sa.Column("actor_actual_role", actor_actual_enum, nullable=False),
        sa.Column(
            "effective_transition_role",
            effective_enum,
            nullable=False,
        ),
        sa.Column("transition_reason", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # PLAN line 1057-1064 actor-consistency invariant.
        sa.CheckConstraint(
            "(transitioned_by_role = 'system' "
            "AND transitioned_by_user_id IS NULL "
            "AND transitioned_by_lead_id IS NULL) "
            "OR (transitioned_by_role IN ('officer', 'admin') "
            "AND transitioned_by_user_id IS NOT NULL "
            "AND transitioned_by_lead_id IS NULL) "
            "OR (transitioned_by_role = 'candidate' "
            "AND transitioned_by_lead_id IS NOT NULL "
            "AND transitioned_by_user_id IS NULL)",
            name="ck_status_history_actor_consistency",
        ),
    )

    # 3. Indexes.
    op.create_index(
        "ix_status_history_profile_occurred",
        "admission_profile_status_history",
        ["profile_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_status_history_to_status",
        "admission_profile_status_history",
        ["to_status"],
    )

    # 4. Backfill block 0 — Initial state (1 row/profile).
    #    Idempotent via WHERE NOT EXISTS per-profile.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 metadata, occurred_at)
            SELECT
                p.id, NULL, p.status,
                'system',  -- legacy column
                'system',  -- actor_actual_role
                'system',  -- effective_transition_role
                jsonb_build_object('backfill', true, 'source', 'phase1_10_initial'),
                p.created_at
            FROM admission_profile p
            WHERE NOT EXISTS (
                SELECT 1 FROM admission_profile_status_history h
                WHERE h.profile_id = p.id
            )
            """
        )
    )

    # NOTE — scattered scalar blocks 1-5 (Codex P1 catch on PR-2A):
    # AdmissionProfile permits the audit-actor scalars
    # (``approved_by_id`` / ``rejected_by_id`` / ``revision_requested_by_id``
    # / ``resubmitted_by_id`` / ``overridden_by_id``) to be NULL while
    # the corresponding ``*_at`` is non-NULL on legacy data
    # (system auto-approval, migration-imported rows, etc.). The
    # CHECK constraint ``ck_status_history_actor_consistency``
    # requires ``transitioned_by_user_id NOT NULL`` when role is
    # ``officer``/``admin``, so a naive backfill would violate the
    # check on those rows.
    #
    # Fix: each block uses ``CASE WHEN p.<actor>_by_id IS NULL THEN
    # 'system' ELSE '<role>'`` for all THREE role columns
    # (transitioned_by_role legacy + actor_actual_role + effective_
    # transition_role). When actor is NULL, the row classifies as
    # system actor (CHECK first OR clause: role='system' AND
    # user_id NULL AND lead_id NULL) and an ``actor_fallback`` flag
    # in metadata records the substitution for admin queue review.

    # 5. Backfill block 1 — Approved transitions.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_user_id,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 transition_reason, occurred_at, metadata)
            SELECT
                p.id, 'submitted', 'approved',
                p.approved_by_id,
                (CASE WHEN p.approved_by_id IS NULL THEN 'system' ELSE 'admin' END)::transition_role_legacy,
                (CASE WHEN p.approved_by_id IS NULL THEN 'system' ELSE COALESCE(u.role::text, 'admin') END)::actor_actual_role,
                (CASE WHEN p.approved_by_id IS NULL THEN 'system' ELSE 'admin' END)::effective_transition_role,
                p.approval_notes,
                p.approved_at,
                jsonb_build_object(
                    'source', 'scattered_scalar_backfill',
                    'transition', 'approved',
                    'actor_fallback', (p.approved_by_id IS NULL)
                )
            FROM admission_profile p
            LEFT JOIN "user" u ON u.id = p.approved_by_id
            WHERE p.approved_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admission_profile_status_history h
                  WHERE h.profile_id = p.id
                    AND h.to_status = 'approved'
                    AND h.metadata->>'source' = 'scattered_scalar_backfill'
              )
            """
        )
    )

    # 6. Backfill block 2 — Rejected transitions.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_user_id,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 transition_reason, occurred_at, metadata)
            SELECT
                p.id, 'submitted', 'rejected',
                p.rejected_by_id,
                (CASE WHEN p.rejected_by_id IS NULL THEN 'system' ELSE 'admin' END)::transition_role_legacy,
                (CASE WHEN p.rejected_by_id IS NULL THEN 'system' ELSE COALESCE(u.role::text, 'admin') END)::actor_actual_role,
                (CASE WHEN p.rejected_by_id IS NULL THEN 'system' ELSE 'admin' END)::effective_transition_role,
                p.rejection_reason,
                p.rejected_at,
                jsonb_build_object(
                    'source', 'scattered_scalar_backfill',
                    'transition', 'rejected',
                    'actor_fallback', (p.rejected_by_id IS NULL)
                )
            FROM admission_profile p
            LEFT JOIN "user" u ON u.id = p.rejected_by_id
            WHERE p.rejected_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admission_profile_status_history h
                  WHERE h.profile_id = p.id
                    AND h.to_status = 'rejected'
                    AND h.metadata->>'source' = 'scattered_scalar_backfill'
              )
            """
        )
    )

    # 7. Backfill block 3 — Revision requested transitions.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_user_id,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 transition_reason, occurred_at, metadata)
            SELECT
                p.id, 'submitted', 'revision_requested',
                p.revision_requested_by_id,
                (CASE WHEN p.revision_requested_by_id IS NULL THEN 'system' ELSE 'admin' END)::transition_role_legacy,
                (CASE WHEN p.revision_requested_by_id IS NULL THEN 'system' ELSE COALESCE(u.role::text, 'admin') END)::actor_actual_role,
                (CASE WHEN p.revision_requested_by_id IS NULL THEN 'system' ELSE 'admin' END)::effective_transition_role,
                p.revision_reason,
                p.revision_requested_at,
                jsonb_build_object(
                    'source', 'scattered_scalar_backfill',
                    'transition', 'revision_requested',
                    'actor_fallback', (p.revision_requested_by_id IS NULL)
                )
            FROM admission_profile p
            LEFT JOIN "user" u ON u.id = p.revision_requested_by_id
            WHERE p.revision_requested_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admission_profile_status_history h
                  WHERE h.profile_id = p.id
                    AND h.to_status = 'revision_requested'
                    AND h.metadata->>'source' = 'scattered_scalar_backfill'
              )
            """
        )
    )

    # 8. Backfill block 4 — Resubmitted transitions. Officer is
    #    the typical actor; system fallback when by_id NULL.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_user_id,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 transition_reason, occurred_at, metadata)
            SELECT
                p.id, 'revision_requested', 'resubmitted',
                p.resubmitted_by_id,
                (CASE WHEN p.resubmitted_by_id IS NULL THEN 'system' ELSE 'officer' END)::transition_role_legacy,
                (CASE WHEN p.resubmitted_by_id IS NULL THEN 'system' ELSE COALESCE(u.role::text, 'officer') END)::actor_actual_role,
                (CASE WHEN p.resubmitted_by_id IS NULL THEN 'system' ELSE 'officer' END)::effective_transition_role,
                p.resubmit_notes,
                p.resubmitted_at,
                jsonb_build_object(
                    'source', 'scattered_scalar_backfill',
                    'transition', 'resubmitted',
                    'actor_fallback', (p.resubmitted_by_id IS NULL)
                )
            FROM admission_profile p
            LEFT JOIN "user" u ON u.id = p.resubmitted_by_id
            WHERE p.resubmitted_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admission_profile_status_history h
                  WHERE h.profile_id = p.id
                    AND h.to_status = 'resubmitted'
                    AND h.metadata->>'source' = 'scattered_scalar_backfill'
              )
            """
        )
    )

    # 9. Backfill block 5 — Overridden transitions. Admin only;
    #    system fallback when by_id NULL.
    op.execute(
        sa.text(
            """
            INSERT INTO admission_profile_status_history
                (profile_id, from_status, to_status,
                 transitioned_by_user_id,
                 transitioned_by_role, actor_actual_role,
                 effective_transition_role,
                 transition_reason, occurred_at, metadata)
            SELECT
                p.id, 'rejected', 'overridden',
                p.overridden_by_id,
                (CASE WHEN p.overridden_by_id IS NULL THEN 'system' ELSE 'admin' END)::transition_role_legacy,
                (CASE WHEN p.overridden_by_id IS NULL THEN 'system' ELSE COALESCE(u.role::text, 'admin') END)::actor_actual_role,
                (CASE WHEN p.overridden_by_id IS NULL THEN 'system' ELSE 'admin' END)::effective_transition_role,
                NULL,  -- override reason not in scattered scalar; admin notes via UI later
                p.overridden_at,
                jsonb_build_object(
                    'source', 'scattered_scalar_backfill',
                    'transition', 'overridden',
                    'actor_fallback', (p.overridden_by_id IS NULL)
                )
            FROM admission_profile p
            LEFT JOIN "user" u ON u.id = p.overridden_by_id
            WHERE p.overridden_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admission_profile_status_history h
                  WHERE h.profile_id = p.id
                    AND h.to_status = 'overridden'
                    AND h.metadata->>'source' = 'scattered_scalar_backfill'
              )
            """
        )
    )


def downgrade() -> None:
    # Inverse — drop indexes, then table, then ENUMs in reverse
    # creation order.
    op.drop_index(
        "ix_status_history_to_status",
        table_name="admission_profile_status_history",
    )
    op.drop_index(
        "ix_status_history_profile_occurred",
        table_name="admission_profile_status_history",
    )
    op.drop_table("admission_profile_status_history")

    for enum_values, name in [
        (EFFECTIVE_TRANSITION_ROLE_VALUES, "effective_transition_role"),
        (ACTOR_ACTUAL_ROLE_VALUES, "actor_actual_role"),
        (TRANSITION_ROLE_LEGACY_VALUES, "transition_role_legacy"),
    ]:
        enum = postgresql.ENUM(
            *enum_values, name=name, create_type=False,
        )
        enum.drop(op.get_bind(), checkfirst=True)
