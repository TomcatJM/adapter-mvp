#!/usr/bin/env bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"

DELIVERY_MODE="ci"
TASK_ID="ci-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"
HOST_ID="${ADAPTER_HOST_ID:-host-47-116-102-238}"

if [ "${DELIVERY_MODE}" != "ci" ]; then
  echo "CI pipeline can only run with DELIVERY_MODE=ci" >&2
  exit 1
fi

echo "DELIVERY_MODE=${DELIVERY_MODE}"
echo "TASK_ID=${TASK_ID}"
echo "=== Adapter CI preview ==="

curl -sS -X POST "${BASE_URL}/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "'"${HOST_ID}"'",
    "execute": false
  }'

echo ""
