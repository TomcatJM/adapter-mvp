#!/usr/bin/env bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"
: "${REQUIREMENT_ID:?REQUIREMENT_ID is required for release}"

DELIVERY_MODE="release"
TASK_ID="rel-${REQUIREMENT_ID}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
YUNXIAO_APPROVAL_ID="yx-approval-${REQUIREMENT_ID}-${BUILD_NUMBER:-0}"
BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"
HOST_ID="${ADAPTER_HOST_ID:-host-47-116-102-238}"

case "${BRANCH_NAME:-}" in
  develop|release/*|master|main|"") ;;
  *)
    echo "Release pipeline cannot run on branch: ${BRANCH_NAME}" >&2
    exit 1
    ;;
esac

if [ "${DELIVERY_MODE}" != "release" ]; then
  echo "Execute can only run with DELIVERY_MODE=release" >&2
  exit 1
fi

echo "DELIVERY_MODE=${DELIVERY_MODE}"
echo "REQUIREMENT_ID=${REQUIREMENT_ID}"
echo "TASK_ID=${TASK_ID}"
echo "YUNXIAO_APPROVAL_ID=${YUNXIAO_APPROVAL_ID}"

# 1. preview
echo "=== Adapter release preview ==="
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

# 2. audit preview
echo "=== Adapter preview audit ==="
AUDIT_JSON=$(curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/audit/${TASK_ID}")
echo "${AUDIT_JSON}"
echo "${AUDIT_JSON}" | grep -q '"event"[[:space:]]*:[[:space:]]*"preview"'
echo "${AUDIT_JSON}" | grep -q '"status"[[:space:]]*:[[:space:]]*"PREVIEWED"'

# 3. execute: 本脚本只能放在人工审批后的云效 Shell 节点执行。
echo "=== Adapter release execute ==="
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

# 4. status
echo "=== Adapter status ==="
STATUS_JSON=$(curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/status/${TASK_ID}")
echo "${STATUS_JSON}"
echo "${STATUS_JSON}" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCESS"'

# 5. final audit
echo "=== Adapter final audit ==="
FINAL_AUDIT_JSON=$(curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/audit/${TASK_ID}")
echo "${FINAL_AUDIT_JSON}"
echo "${FINAL_AUDIT_JSON}" | grep -q '"event"[[:space:]]*:[[:space:]]*"preview"'
echo "${FINAL_AUDIT_JSON}" | grep -q '"event"[[:space:]]*:[[:space:]]*"execute"'
echo "${FINAL_AUDIT_JSON}" | grep -q '"event"[[:space:]]*:[[:space:]]*"status"'
echo "${FINAL_AUDIT_JSON}" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCESS"'
