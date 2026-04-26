"""seed Casbin policy for POST /api/admissions/{id}/minor-correction

Revision ID: dd5m6n7o8p9q
Revises: dd4l5m6n7o8p
Create Date: 2026-04-25

Casbin enforcer reads policies from the ``casbin_rule`` table at request
time, so adding entries to ``policy_templates.py`` alone is not enough —
without an INSERT migration the route returns 403 for every caller.

Per-profile IDOR (admin all / manager same-unit / officer same-unit AND
assigned) is enforced inside ``get_admission_for_user`` (deps.py:2240),
so granting role-level access here is safe — the dependency narrows
scope before the service runs.

Pattern matches existing policies (verified live on production
2026-04-25): ``/api/admissions/{id}/submit``,
``/api/admissions/{id}/resubmit``, ``/api/admissions/{id}/documents/{doc_code}/upload``
all use ``{id}`` literal placeholder, NOT ``*`` wildcard. Casbin matcher
is configured for keyMatch over ``{id}``, so plan must follow.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "dd5m6n7o8p9q"
down_revision: Union[str, None] = "dd4l5m6n7o8p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_POLICIES = [
    # Admin wildcard row covers admin globally, but seeding the explicit
    # row keeps grep-by-route audits self-contained.
    ("role:admin", "/api/admissions/{id}/minor-correction", "POST"),
    ("role:manager", "/api/admissions/{id}/minor-correction", "POST"),
    ("role:officer", "/api/admissions/{id}/minor-correction", "POST"),
]


def upgrade() -> None:
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{subject}', '{obj}', '{action}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = '{subject}'
                  AND v1 = '{obj}'
                  AND v2 = '{action}'
            )
            """
        )


def downgrade() -> None:
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{obj}'
              AND v2 = '{action}'
            """
        )
