"""Seed missing read grants surfaced by finance Chrome smoke.

The finance invoice page loads inside the shared dashboard shell. For an
accountant session, Chrome smoke must not produce background 403s from shell
queries while the invoice filter picker APIs are loading.

All three grants below ALREADY exist as template policy
(``policy_templates.py``): ``/api/notifications/preferences`` GET in
``BASIC_USER_TEMPLATE``; ``/api/finance/dashboard`` GET in
``ACCOUNTANT_TEMPLATE``; ``/api/organization-units`` GET in BOTH
``OFFICER_TEMPLATE`` (accountant inherits it via the ``role:accountant ->
role:officer`` g-edge) AND, declared directly, ``ACCOUNTANT_TEMPLATE`` (so a
``refresh_role_from_template`` re-sync that wipes+re-adds only a role's own
template rows keeps this direct accountant grant — without the template entry
the re-sync would drop the runtime row seeded here). This migration only HEALS
runtime drift — it re-seeds rows the templates guarantee but that a stale
runtime policy table may be missing. The ``/api/organization-units`` direct
accountant grant is defensive belt-and-braces for the new "Đơn vị" invoice
filter dropdown, since runtime inheritance has drifted before (cf.
``tcf20260626001`` for ``/api/programs`` and ``tcf20260627001`` for
``/api/admin/users``).

Because the grants are template-owned, ``downgrade()`` is intentionally a
no-op: ``upgrade()`` is conditional (``WHERE NOT EXISTS``) so on a normal env
the rows pre-date this migration, and an unconditional delete on downgrade
would strip legitimate template policy (403s on the finance dashboard /
notification preferences / unit picker) rather than reverting only what this
migration created.

Revision ID: tcf20260627002
Revises: tcf20260627001
Create Date: 2026-06-27
"""

from alembic import op
from sqlalchemy import text


revision = "tcf20260627002"
down_revision = "tcf20260627001"
branch_labels = None
depends_on = None


_GRANTS = [
    # Basic self-service notification preferences; inherited by staff roles.
    ("role:user", "/api/notifications/preferences", "GET", "user"),
    # Finance overview request used by finance workspace shell/cards.
    ("role:accountant", "/api/finance/dashboard", "GET", "accountant"),
    # Unit list powering the new "Đơn vị" invoice filter dropdown. Officer-tier
    # endpoint (accountant inherits) — direct grant heals any runtime drift.
    ("role:accountant", "/api/organization-units", "GET", "accountant"),
]


def upgrade() -> None:
    for v0, v1, v2, template_id in _GRANTS:
        op.execute(
            text(
                f"""
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p', '{v0}', '{v1}', '{v2}', 'allow', '{template_id}', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
                )
                """
            )
        )
        # Self-heal any pre-existing row with a NULL eft (v3) — without
        # 'allow' the policy is dropped on load_policy.
        op.execute(
            text(
                f"""
                UPDATE casbin_rule SET v3 = CAST('allow' AS VARCHAR)
                WHERE ptype = 'p'
                  AND v3 IS NULL
                  AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
                """
            )
        )
    print(f"[tcf20260627002] Seeded {len(_GRANTS)} smoke support Casbin grants")


def downgrade() -> None:
    # No-op by design: every grant above is template-owned policy that
    # pre-dates this migration (upgrade is conditional WHERE NOT EXISTS).
    # Deleting them on downgrade would remove legitimate template grants,
    # not revert this migration's own additions.
    pass
