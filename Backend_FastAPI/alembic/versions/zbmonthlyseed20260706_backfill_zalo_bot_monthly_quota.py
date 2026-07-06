"""Backfill zalo_bot MONTHLY quota from this month's sends (daily->monthly cutover)

Revision ID: zbmonthlyseed20260706
Revises: smsp2retidx20260705001
Create Date: 2026-07-06

The notification quota for the ``zalo_bot`` channel switched from a DAILY cap to
a MONTHLY cap (Zalo Bot free tier = 3000 msg/month, no hard daily cap).
``check_quota`` now reads ONLY the monthly row, so a mid-month cutover would
forget any messages already sent this month under the old daily counter and
could allow a full month's allowance ON TOP of them -- overshooting the
provider's 3000/month cap.

This one-time data migration seeds the current month's monthly ``zalo_bot``
quota row with the count of messages already sent this month (from
``notification_delivery``), BEFORE the new monthly enforcement starts serving
(it runs in the entrypoint ``alembic upgrade head`` before uvicorn/celery
process any delivery). Idempotent + race-safe: ``ON CONFLICT`` keeps the
GREATEST of the existing and backfilled count, so the app / beat task lazily
creating the row concurrently cannot lower it.

Leftover daily ``zalo_bot`` rows are intentionally NOT deleted (kept for
rollback safety -- the reverted daily code resumes from them). They no longer
affect enforcement; at worst they cause a transient, self-healing admin-
dashboard duplicate on the cutover day only.
"""
import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic. (<=32 chars for version_num column.)
revision = "zbmonthlyseed20260706"
down_revision = "smsp2retidx20260705001"
branch_labels = None
depends_on = None


def _seed_sql(limit: int) -> str:
    """Build the backfill statement.

    ``limit`` is ``int()``-coerced from config, so inlining it as a literal is
    injection-safe AND avoids a prepared-statement parameter being deduced as
    both integer (the ``quota_limit`` column) and bigint (compared against
    ``count(*)``), which asyncpg rejects as an ambiguous type.
    """
    return f"""
    INSERT INTO notification_quota
        (channel, provider, period, period_start, quota_limit, quota_used, blocked)
    SELECT
        'zalo_bot', 'zalo_bot', 'monthly',
        date_trunc('month', CURRENT_DATE)::date,
        {limit},
        s.cnt,
        s.cnt >= {limit}
    FROM (
        SELECT count(*) AS cnt
        FROM notification_delivery
        WHERE channel = 'zalo_bot'
          AND status IN ('sent', 'delivered', 'read')
          AND created_at >= date_trunc('month', CURRENT_DATE)
    ) s
    ON CONFLICT (channel, provider, period, period_start)
    DO UPDATE SET
        quota_used = GREATEST(
            notification_quota.quota_used, EXCLUDED.quota_used
        ),
        blocked = GREATEST(
            notification_quota.quota_used, EXCLUDED.quota_used
        ) >= notification_quota.quota_limit,
        updated_at = now()
    """


_DOWNGRADE_SQL = """
DELETE FROM notification_quota
WHERE channel = 'zalo_bot'
  AND period = 'monthly'
  AND period_start = date_trunc('month', CURRENT_DATE)::date
"""


def upgrade() -> None:
    # Read the limit from the same env var Settings uses, defaulting to the
    # config default so the seeded row's cap matches the running app.
    limit = int(os.environ.get("ZALO_BOT_MONTHLY_QUOTA") or 2800)
    op.get_bind().execute(sa.text(_seed_sql(limit)))


def downgrade() -> None:
    # Remove only the current month's seeded monthly row; the untouched daily
    # rows let the reverted daily-quota code resume without data loss.
    op.get_bind().execute(sa.text(_DOWNGRADE_SQL))
