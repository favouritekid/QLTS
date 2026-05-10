"""Phase 2 v8.2 PR-2D: PathSubjectGroupConfig + Item (path-level subject group config)

Plan v8.2 PR-2D scope:
- ``path_subject_group_config`` table — path-level subject group config
  với min_score / min_subject_score / group_quota override above
  CriteriaSubjectGroup default
- ``path_subject_group_item`` table — per-subject item override (is_principal,
  min_subject_score) with composite invariant guard
  ``subject_group_subject.subject_group_id == config.subject_group_id``
- Backfill ``path_subject_group_config`` from ``criteria_subject_group``
  ON CONFLICT DO NOTHING (each path's criteria has 1:N subject groups)

Tier 3 quota chain (PR-2D scope):
- ``∑(group_quota in path) ≤ path.admit_quota``
- Service-layer guard cho admin set group_quota change

Composite invariant guard:
- subject_group_subject.subject_group_id == path_subject_group_config.subject_group_id
- Service-layer assert (NOT DB-level FK) per ADM-003 invariant style

Revision ID: phase2_05
Revises: phase2_04
Create Date: 2026-05-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "phase2_05"
down_revision: Union[str, None] = "phase2_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # Table 1: path_subject_group_config (CREATE IF NOT EXISTS)
    # ============================================================
    # IF NOT EXISTS guard — Base.metadata.create_all() can pre-create
    # tables when backend autoreloads model file before alembic apply.
    # Safe per memory test-db-schema-source pattern.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS path_subject_group_config (
            id SERIAL PRIMARY KEY,
            admission_path_id INTEGER NOT NULL
                REFERENCES admission_path(id) ON DELETE CASCADE,
            subject_group_id INTEGER NOT NULL
                REFERENCES subject_group(id) ON DELETE CASCADE,
            min_score NUMERIC(8,2),
            min_subject_score NUMERIC(8,2),
            group_quota INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_path_subject_group_config_path_group
                UNIQUE (admission_path_id, subject_group_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_path_subject_group_config_admission_path_id "
        "ON path_subject_group_config(admission_path_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_path_subject_group_config_subject_group_id "
        "ON path_subject_group_config(subject_group_id)"
    )

    # ============================================================
    # Table 2: path_subject_group_item (CREATE IF NOT EXISTS)
    # ============================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS path_subject_group_item (
            id SERIAL PRIMARY KEY,
            path_subject_group_config_id INTEGER NOT NULL
                REFERENCES path_subject_group_config(id) ON DELETE CASCADE,
            subject_group_subject_id INTEGER NOT NULL
                REFERENCES subject_group_subject(id) ON DELETE CASCADE,
            is_principal BOOLEAN NOT NULL DEFAULT FALSE,
            min_subject_score NUMERIC(8,2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_path_subject_group_item
                UNIQUE (path_subject_group_config_id, subject_group_subject_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_path_subject_group_item_config_id "
        "ON path_subject_group_item(path_subject_group_config_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_path_subject_group_item_sgs_id "
        "ON path_subject_group_item(subject_group_subject_id)"
    )

    # ============================================================
    # Backfill path_subject_group_config từ criteria_subject_group
    # ============================================================
    # Mỗi path có criteria, criteria có 1:N subject_group via
    # criteria_subject_group. Backfill creates 1 path_subject_group_config
    # row per (path, subject_group) tuple. ON CONFLICT skip duplicates.
    op.execute(
        """
        INSERT INTO path_subject_group_config (
            admission_path_id, subject_group_id,
            min_score, min_subject_score, group_quota,
            created_at, updated_at
        )
        SELECT DISTINCT
            ap.id AS admission_path_id,
            csg.subject_group_id AS subject_group_id,
            ac.min_score,
            ac.min_subject_score,
            NULL::integer AS group_quota,
            now(),
            now()
        FROM admission_path ap
        JOIN admission_criteria ac ON ac.id = ap.criteria_id
        JOIN criteria_subject_group csg ON csg.criteria_id = ac.id
        WHERE ap.criteria_id IS NOT NULL
        ON CONFLICT (admission_path_id, subject_group_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("path_subject_group_item")
    op.drop_table("path_subject_group_config")
