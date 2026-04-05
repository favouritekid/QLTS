#!/bin/bash
set -e

echo "=== Running Alembic migrations ==="
alembic upgrade head

echo "=== Syncing notification rules ==="
python -m app.scripts.sync_notification_rules

echo "=== Startup complete. Starting application ==="
exec "$@"
