"""phase1_13: create system_config table + seed current_intake_year=2026

Revision ID: phase1_13
Revises: phase1_08
Create Date: 2026-05-04

#184 Wave 1 PR-1D — ninth migration in Phase 1 Schema chain
(PLAN §4 line 90 + 3459 + RISK_REVIEW B4 P0). **Closes B4 P0
blocker** — system_config table + ``current_intake_year`` key were
called out as missing in the cold cutover RISK_REVIEW.

Schema
------
* ``system_config``:
  - ``key`` text PK — config key (e.g. ``current_intake_year``,
    ``cutover_freeze_active``, ``zalo_template_approved``).
  - ``value`` JSONB NOT NULL — config value (any JSON shape so
    the same table holds bools, ints, lists, nested objects).
  - ``description`` text nullable — admin-facing docstring.
  - ``updated_at`` timestamptz NOT NULL DEFAULT now() — last admin
    change audit trail (in addition to ``activity_log`` row that
    SystemConfigService writes).
  - ``updated_by_user_id`` integer FK → ``user(id)`` ON DELETE
    SET NULL — admin who last changed; SET NULL on user delete
    so the audit row survives.

* PK ``(key)`` — text PK chosen instead of integer PK because
  callers query by key directly (``SELECT value FROM
  system_config WHERE key = 'current_intake_year'``). No range
  scans, no FK targets, no need for sequential ID.

Seed
----
Single seed row per PLAN line 3459 + RISK_REVIEW B4:

* ``current_intake_year = 2026`` (JSONB integer).

Idempotent via ``ON CONFLICT (key) DO NOTHING`` — re-running
upgrade after partial failure leaves the existing row untouched.

Service / router
----------------
Service ``SystemConfigService`` lives at
``app/services/system_config_service.py`` (admin-only governance
guard). Router ``app/routers/admin_v2_system_config.py`` exposes
GET / PATCH endpoints under ``/api/v2/admin/system-config``,
mirroring the T0-5 admin_v2_casbin pattern.

Down-revision chain: ``phase1_08 → phase1_13``. Note slot
``phase1_09 / phase1_10 / phase1_11 / phase1_12 / phase1_14
through phase1_19a`` are reserved by the wave plan for Wave 2-5
migrations; chain order follows ship order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "phase1_13"
down_revision: Union[str, None] = "phase1_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_config",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column(
            "value",
            JSONB(),
            nullable=False,
            comment="Config value — any JSON shape (bool, int, list, nested object)",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Seed `current_intake_year=2026` — closes B4 P0.
    op.execute(
        sa.text(
            """
            INSERT INTO system_config (key, value, description)
            VALUES (
                'current_intake_year',
                '2026'::jsonb,
                'Năm tuyển sinh hiện tại — hiển thị mặc định trên FE storefront và admin Phase 3 wizard'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("system_config")
