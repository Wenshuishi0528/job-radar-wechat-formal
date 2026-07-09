#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi
export JOB_RADAR_PERSONAL_MODE="${JOB_RADAR_PERSONAL_MODE:-1}"
export ENABLE_WECHAT_PUBLIC_FETCH="${ENABLE_WECHAT_PUBLIC_FETCH:-1}"
export ENABLE_WEB_SEARCH_IMPORT="${ENABLE_WEB_SEARCH_IMPORT:-1}"
uvicorn services.api.main:app --reload --host 127.0.0.1 --port "${JOB_RADAR_PORT:-8000}"
