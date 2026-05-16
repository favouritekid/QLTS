"""Hotfix: Sweep ANY casbin_rule policy rows with NULL eft (v3).

Revision ID: qae2e02
Revises: qae2e01
Create Date: 2026-05-16

**Regression W4-1** (post-PR #297 deploy 2026-05-16): qae2e01 INSERT
omitted v3 (eft) column → row 924 `role:manager /api/leads/export GET`
NULL v3 → Casbin model `p = sub, obj, act, eft` raises RuntimeError
"invalid policy size" trên load_policy() → ALL admission endpoints
crash 500 (manifest qua "GET /api/admissions/{id} → 500" trên FE).

User dev fix manual UPDATE row 924 v3='allow'. Prod chưa apply qae2e01
(version=phase3_01 tại thời điểm hotfix) → cần migration đảm bảo cả 2
guarantees:

1. **qae2e01 source** đã được patch include v3 column → fresh
   deploys/installs sẽ INSERT đúng.
2. **qae2e02** (this) sweep ANY NULL v3 'p' rows (defense in depth):
   - Dev: row 924 đã fix manual, NULL=0, no-op
   - Prod: khi deploy chain qae2e01 → qae2e02 chạy ngay sau → guarantee
     không còn NULL trước khi app khởi động Casbin reload
   - Catches old migrations (bb2j3k4l5m6n, dd5m6n7o8p9q,
     idor20260216001, etc.) cũng có pattern same bug nhưng prod chưa
     surface (rows có thể được template re-seed cover trong bootstrap)

Default `allow` chọn vì:
- Tất cả NULL eft rows hiện được INSERT bởi migration "add allow policy",
  không bao giờ deny (deny rules luôn explicit eft='deny' trong
  policy_templates.py).
- Casbin matcher fail-closed nếu no allow match → defensive default.

Idempotent + safe re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "qae2e02"
down_revision: Union[str, None] = "qae2e01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sweep NULL v3 (eft) policy rows → set to 'allow' default.
    # CAST literal to VARCHAR to avoid asyncpg parameter type ambiguity
    # (memory `migration-systemevents-value-case` lesson).
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE casbin_rule
            SET v3 = CAST('allow' AS VARCHAR)
            WHERE ptype = CAST('p' AS VARCHAR)
              AND v3 IS NULL
            """
        )
    )
    # Log count for ops audit visibility — Alembic captures into deploy
    # log so ops can verify how many rows hotfix touched.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                RAISE NOTICE 'qae2e02 hotfix: backfilled % NULL eft row(s) to allow',
                    {result.rowcount};
            END $$;
            """
        )
    )


def downgrade() -> None:
    # No-op: we can't reliably distinguish rows that were hotfixed from
    # rows naturally 'allow'. Downgrading would require an audit log we
    # don't have, and reverting would re-introduce the Casbin crash bug.
    # Per memory `migration-predicate-safety`: only downgrade when safe.
    pass
