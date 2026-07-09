#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

export JOB_RADAR_PERSONAL_MODE="${JOB_RADAR_PERSONAL_MODE:-1}"
export ENABLE_WECHAT_PUBLIC_FETCH="${ENABLE_WECHAT_PUBLIC_FETCH:-1}"
export ENABLE_WEB_SEARCH_IMPORT="${ENABLE_WEB_SEARCH_IMPORT:-1}"
export ENABLE_SOGOU_DISCOVERY="${ENABLE_SOGOU_DISCOVERY:-1}"
export SOGOU_REQUEST_DELAY_SECONDS="${SOGOU_REQUEST_DELAY_SECONDS:-2.0}"
export WEB_SEARCH_REQUEST_DELAY_SECONDS="${WEB_SEARCH_REQUEST_DELAY_SECONDS:-1.0}"
export JOB_RADAR_USER_AGENT="${JOB_RADAR_USER_AGENT:-JobRadar/0.6 personal-local-use no-login-cookie contact=operator}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python 3 first, then run this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating local Python environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

echo "Installing/updating dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ -z "${JOB_RADAR_PORT:-}" ]]; then
  JOB_RADAR_PORT="$(python - <<'PY'
import socket

for port in range(8000, 8020):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit("No free port found from 8000 to 8019")
PY
)"
fi

URL="http://127.0.0.1:${JOB_RADAR_PORT}"
echo ""
echo "Job Radar is starting in personal local mode."
echo "Open this address if the browser does not open automatically:"
echo "${URL}"
echo ""
echo "Leave this Terminal window open while using the app."
echo "Press Control-C here to stop it."
echo ""

(sleep 2 && open "${URL}") >/dev/null 2>&1 &
exec python -m uvicorn services.api.main:app --host 127.0.0.1 --port "${JOB_RADAR_PORT}"
