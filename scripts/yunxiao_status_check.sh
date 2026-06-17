#!/usr/bin/env bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"

# status：查询同一个 TASK_ID 的执行状态。
curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/status/${TASK_ID}"

echo ""
