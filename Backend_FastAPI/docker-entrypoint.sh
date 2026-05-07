#!/bin/bash
set -e

# Cold cutover gates — default behavior preserved cho routine deploy.
# Cả 3 flag cùng họ pattern: exact lowercase "false" mới skip; mọi value khác
# (unset/true/TRUE/typo/...) chạy như cũ. Defensive default: typo → run, không skip.
# Cutover scenario set CẢ 3 flag = false trước deploy backend image mới, sau đó
# manual run alembic + backfill + sync_notification_rules + Casbin reload ngoài
# container start để stream log + time tracking + checkpoint mỗi step.
# Ref: Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md §3.5 T0-1 + §7.2.

# Gate 1: Alembic migrations
if [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" != "false" ]; then
    echo "=== Running Alembic migrations ==="
    alembic upgrade head
else
    echo "=== Skipping Alembic migrations (RUN_MIGRATIONS_ON_STARTUP=false) ==="
fi

# Gate 2: Notification rules sync
# Cutover bundle scenario: B2 ship 12 ADMISSION_* events code; M-1-19b seed DB
# notification_rule rows. Sync script reconcile EVENT_CATALOG ↔ DB. Pre-migration
# (RUN_MIGRATIONS_ON_STARTUP=false) → notification_rule table có thể chưa tồn tại
# hoặc chưa seed → sync sẽ fail/race. Manual run ở T+3:30 sau migration + DB seed.
if [ "${RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP:-true}" != "false" ]; then
    echo "=== Syncing notification rules ==="
    python -m app.scripts.sync_notification_rules
else
    echo "=== Skipping notification rules sync (RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false) ==="
fi

# Gate 3: Casbin enforcer policy load (B1 cold cutover)
# The actual skip happens inside the FastAPI lifespan in `app/main.py` —
# this echo only surfaces the gate state in container logs alongside the
# other two flags so ops can read all three from a single tail. Cutover
# scenario: 4-field auth_model.conf is on the new image but DB still has
# 210 rows with v3 IS NULL until the manual backfill at T+3:00. Loading
# the enforcer against that DB state would crash with `RuntimeError:
# invalid policy size`. Set RUN_CASBIN_LOAD_ON_STARTUP=false so the
# lifespan skips load_policy(); restart at T+3:15 with the flag flipped
# back to true (or unset) re-runs load_policy() against a backfilled DB.
if [ "${RUN_CASBIN_LOAD_ON_STARTUP:-true}" != "false" ]; then
    echo "=== Casbin enforcer policy load ENABLED (lifespan will load on app start) ==="
else
    echo "=== Casbin enforcer policy load DEFERRED (RUN_CASBIN_LOAD_ON_STARTUP=false; lifespan will skip load_policy()) ==="
fi

echo "=== Startup complete. Starting application ==="
exec "$@"
