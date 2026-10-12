#!/usr/bin/env bash
# Wrapper used by cron/launchd/systemd. Loads secrets from the environment file your
# secret manager writes (never committed), then runs the overnight job.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p var/logs
if [[ -f "${MONTHEND_ENV_FILE:-/etc/monthend/env}" ]]; then
  set -a; source "${MONTHEND_ENV_FILE:-/etc/monthend/env}"; set +a
fi
export MONTHEND_MODE=operate
exec .venv/bin/python -m monthend nightly "$@" >> "var/logs/nightly-$(date +%Y%m%d).log" 2>&1
