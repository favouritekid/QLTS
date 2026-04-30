@echo off
REM Run frontend npm scripts (type-check, test, lint, build) in an
REM isolated, throw-away container instead of `docker compose exec`.
REM
REM Why: `exec` shares the dev container's cgroup with the live Next.js
REM dev server. Running tsc / vitest / eslint there has OOM-killed PID 1
REM (Next.js) and produced err_empty_response in browser sessions.
REM `run --rm --no-deps` spawns a fresh container, isolated memory, and
REM auto-removes on exit.
REM
REM Usage:
REM   scripts\fe-check.cmd type-check
REM   scripts\fe-check.cmd test
REM   scripts\fe-check.cmd test:coverage
REM   scripts\fe-check.cmd lint
REM   scripts\fe-check.cmd build
REM
REM Anything passed after the script name goes to `npm run <args...>`.

if "%~1"=="" (
  echo Usage: %~n0 ^<npm-script^> [args...]
  echo Example: %~n0 type-check
  exit /b 64
)

docker compose run --rm --no-deps frontend npm run %*
