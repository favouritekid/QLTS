#!/bin/bash
# QLTS Development - starts all services with frontend HMR file watching
#
# Usage:
#   ./dev.sh          - start services + watch (foreground, Ctrl+C to stop watching)
#   ./dev.sh down     - stop all services
#   ./dev.sh logs     - tail backend + frontend logs
#
# Why watch? On Windows, Docker bind mounts don't propagate inotify
# events. docker compose watch detects host file changes and copies them
# into the container, generating real inotify events for Turbopack HMR.

case "$1" in
  down)
    docker compose down
    ;;
  logs)
    docker compose logs backend frontend -f --tail=30
    ;;
  *)
    echo "Starting QLTS services + file watcher..."
    echo "(Ctrl+C stops watching, services keep running)"
    echo ""
    docker compose watch
    ;;
esac
