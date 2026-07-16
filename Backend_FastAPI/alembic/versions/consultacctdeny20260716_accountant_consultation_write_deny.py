"""deny accountant POST/PUT/DELETE consultations (separation-of-duties)

OFFICER_TEMPLATE grants the consultation write paths to role:officer:
    POST   /api/leads/{id}/consultations
    PUT    /api/leads/{id}/consultations/{consultation_id}
    DELETE /api/leads/{id}/consultations/{consultation_id}

Because role:accountant inherits role:officer (g, role:accountant, role:officer),
those three allow-rows ALSO reach accountant. Only the GET counterpart was ever
denied (migration seeding `/api/leads/{id}/consultations` GET), which left
finance staff able to CREATE / EDIT / DELETE consultations while being unable to
read the list — an asymmetry, not a policy decision. Consultations drive lead
status transitions, so writing them lets accountant move leads through the
pipeline.

Fix: insert explicit accountant DENY rows. Casbin's effect policy (deny
overrides allow) bounces the inherited officer allows → clean 403 at the Casbin
gateway, mirroring the existing /api/leads POST/PUT denies.

Insert WITH v3='deny' — every existing p-row carries an eft; a NULL eft makes
Casbin `load_policy` crash on next reload (memory casbin-insert-must-include-eft).
Idempotent (WHERE NOT EXISTS) so re-runs are safe.

NOTE: editing policy_templates.py alone ships nothing — AUTO_SYNC_TEMPLATES is
False by default and only honoured in development/test (main.py), and
docker-entrypoint.sh has no casbin template-sync step. This migration is the
only automatic write path into casbin_rule. The backend container must be
RESTARTED after upgrade: the enforcer loads policy once per process at lifespan
(load_policy), so a running multi-worker Gunicorn fleet keeps the stale policy
in memory and would enforce the deny on only some workers.

Revision ID: consultacctdeny20260716
Revises: apptacctdeny20260713
Create Date: 2026-07-16
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "consultacctdeny20260716"
down_revision = "apptacctdeny20260713"
branch_labels = None
depends_on = None


# (object, action) pairs mirroring the OFFICER_TEMPLATE consultation grants.
_DENY_TARGETS = [
    ("/api/leads/{id}/consultations", "POST"),
    ("/api/leads/{id}/consultations/{consultation_id}", "PUT"),
    ("/api/leads/{id}/consultations/{consultation_id}", "DELETE"),
]


def upgrade() -> None:
    # template_id='_legacy' khớp các row deny accountant cùng khối
    # (apptacctdeny20260713) → không bị coi orphan bởi logic tracking template.
    for obj, act in _DENY_TARGETS:
        op.execute(
            f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
            SELECT 'p', 'role:accountant', '{obj}', '{act}', 'deny', '_legacy'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = 'role:accountant'
                  AND v1 = '{obj}'
                  AND v2 = '{act}'
            )
            """
        )


def downgrade() -> None:
    for obj, act in _DENY_TARGETS:
        op.execute(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:accountant'
              AND v1 = '{obj}'
              AND v2 = '{act}'
              AND v3 = 'deny'
            """
        )
