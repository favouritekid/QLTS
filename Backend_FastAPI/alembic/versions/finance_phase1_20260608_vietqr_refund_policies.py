"""Finance Phase 1: VietQR config and refund/overpayment Casbin policies.

Revision ID: finance_phase1_20260608
Revises: appfee_finance_20260607
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "finance_phase1_20260608"
down_revision: Union[str, None] = "appfee_finance_20260607"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SYSTEM_CONFIG_SQL = sa.text(
    """
    INSERT INTO system_config (key, value, description, updated_at)
    VALUES (
        'bank_collection_account',
        CAST(:value AS jsonb),
        'Public bank collection account for offline VietQR transfers',
        NOW()
    )
    ON CONFLICT (key) DO NOTHING
    """
)


_POLICIES = [
    ("role:officer", "/api/invoices/{id}/vietqr", "GET", "allow"),
    ("role:accountant", "/api/finance/debt-report", "GET", "allow"),
    ("role:accountant", "/api/invoices/{id}/vietqr", "GET", "allow"),
    ("role:accountant", "/api/refunds", "GET", "allow"),
    ("role:accountant", "/api/refunds", "POST", "allow"),
    ("role:accountant", "/api/refunds/{id}", "GET", "allow"),
    ("role:accountant", "/api/refunds/{id}/process", "POST", "allow"),
    ("role:accountant", "/api/overpayments", "GET", "allow"),
    ("role:accountant", "/api/overpayments/{id}", "GET", "allow"),
    ("role:accountant", "/api/overpayments/{id}/apply", "POST", "allow"),
    ("role:accountant", "/api/overpayments/{id}/refund", "POST", "allow"),
    ("role:manager", "/api/finance/debt-report", "GET", "allow"),
    ("role:manager", "/api/refunds", "GET", "allow"),
    ("role:manager", "/api/refunds/{id}", "GET", "allow"),
    ("role:manager", "/api/refunds/{id}/approve", "POST", "allow"),
    ("role:manager", "/api/refunds/{id}/reject", "POST", "allow"),
    ("role:manager", "/api/overpayments", "GET", "allow"),
    ("role:manager", "/api/overpayments/{id}", "GET", "allow"),
    ("role:manager", "/api/overpayments/{id}/write-off", "POST", "allow"),
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        _SYSTEM_CONFIG_SQL,
        {
            "value": (
                '{"bank_bin":"","account_number":"","account_name":""}'
            )
        },
    )

    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule
                    (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_finance_phase1_20260608',
                       NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype='p'
                      AND v0=CAST(:v0 AS VARCHAR)
                      AND v1=CAST(:v1 AS VARCHAR)
                      AND v2=CAST(:v2 AS VARCHAR)
                      AND v3=CAST(:v3 AS VARCHAR)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
    conn.execute(
        sa.text(
            """
            DELETE FROM system_config
            WHERE key = 'bank_collection_account'
              AND value = CAST(:value AS jsonb)
            """
        ),
        {"value": '{"bank_bin":"","account_number":"","account_name":""}'},
    )
