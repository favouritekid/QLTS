#!/usr/bin/env bash
# Run frontend npm scripts (type-check, test, lint, build) in an
# isolated, throw-away container instead of `docker compose exec`.
#
# Why: `exec` shares the dev container's cgroup with the live Next.js
# dev server. Running tsc / vitest / eslint there has OOM-killed PID 1
# (Next.js) and produced `err_empty_response` in browser sessions.
# `run --rm --no-deps` spawns a fresh container, isolated memory, and
# auto-removes on exit.
#
# Usage:
#   scripts/fe-check.sh type-check
#   scripts/fe-check.sh test
#   scripts/fe-check.sh test:coverage
#   scripts/fe-check.sh lint
#   scripts/fe-check.sh build
#
# Anything passed after the script name goes to `npm run <args...>`.

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: $(basename "$0") <npm-script> [args...]" >&2
  echo "Example: $(basename "$0") type-check" >&2
  exit 64
fi

exec docker compose run --rm --no-deps frontend npm run "$@"
