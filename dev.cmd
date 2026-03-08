@echo off
REM QLTS Development - starts all services with frontend HMR file watching
REM
REM Usage:
REM   dev          - start services + watch (foreground, Ctrl+C to stop watching)
REM   dev down     - stop all services
REM   dev logs     - tail backend + frontend logs
REM
REM Why --watch? On Windows, Docker bind mounts don't propagate inotify
REM events. docker compose watch detects host file changes and copies them
REM into the container, generating real inotify events for Turbopack HMR.

if "%1"=="down" (
    docker compose down
    exit /b
)

if "%1"=="logs" (
    docker compose logs backend frontend -f --tail=30
    exit /b
)

echo Starting QLTS services + file watcher...
echo (Ctrl+C stops watching, services keep running)
echo.
docker compose watch
