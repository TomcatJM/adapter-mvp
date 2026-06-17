#!/usr/bin/env bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"
HOST_ID="${ADAPTER_HOST_ID:-host-47-116-102-238}"

# 1. preview：只预览，不执行远端动作
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
echo "---- audit ----"

# 2. audit：查询同一个 TASK_ID 的审计记录，验证已入库
curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/audit/${TASK_ID}"

echo ""
