#!/usr/bin/env bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"
: "${YUNXIAO_APPROVAL_ID:?YUNXIAO_APPROVAL_ID is required before execute}"

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"
HOST_ID="${ADAPTER_HOST_ID:-host-47-116-102-238}"

# execute：真实执行远端动作。必须由云效审批/人工审批节点注入 YUNXIAO_APPROVAL_ID。
curl -sS -X POST "${BASE_URL}/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "'"${HOST_ID}"'",
    "execute": true,
    "approvalId": "'"${YUNXIAO_APPROVAL_ID}"'"
  }'

echo ""
