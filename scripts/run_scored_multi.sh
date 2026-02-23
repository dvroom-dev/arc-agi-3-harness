#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${ARC_API_KEY:-}" ]]; then
  echo "ERROR: ARC_API_KEY is not set. Put ARC_API_KEY=... in .env" >&2
  exit 1
fi

SESSION_NAME="${1:-run-api-multi-live-$(date +%Y%m%d-%H%M%S)}"

args=(
  --operation-mode ONLINE
  --arc-backend api
  --scorecard-session-preflight
  --open-scorecard
  --game-ids ls20,ft09,vc33
  --session-name "$SESSION_NAME"
)

if [[ -n "${ARC_OWNER_CHECK_ID:-}" ]]; then
  args+=(--scorecard-owner-check-id "$ARC_OWNER_CHECK_ID")
fi

exec uv run python harness.py "${args[@]}"
