#!/usr/bin/env bash
set -Eeuo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"
: "${REQUIREMENT_ID:?REQUIREMENT_ID is required for release}"

BASE_URL="${ADAPTER_BASE_URL:-http://47.116.102.238:18080}"
HOST_ID="${ADAPTER_HOST_ID:-host-47-116-102-238}"
DELIVERY_MODE="release"
BUILD_NO="${BUILD_NUMBER:-0}"
TASK_ID="rel-${REQUIREMENT_ID}-${BUILD_NO}"
OPERATOR="${BUILD_USER:-yunxiao}"
DEFAULT_APPROVAL_ID="yx-approval-${REQUIREMENT_ID}-${BUILD_NO}"
YUNXIAO_APPROVAL_ID="${YUNXIAO_APPROVAL_ID:-${DEFAULT_APPROVAL_ID}}"
STAGE_NAME="init"
LOG_FILE="${WORKSPACE:-.}/adapter-release-main.log"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

on_error() {
  local exit_code=$?
  local log_tail
  log_tail=$(tail -n 200 "${LOG_FILE}" 2>/dev/null | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g')

  echo "=== Adapter release main failed ==="
  echo "stage=${STAGE_NAME}"
  echo "exit=${exit_code}"

  curl -sS -X POST "${BASE_URL}/callbacks/yunxiao/pipeline-failure" \
    -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{
      "taskId": "'"${TASK_ID}"'",
      "pipelineId": "'"${PIPELINE_ID:-manual}"'",
      "buildNumber": "'"${BUILD_NUMBER:-0}"'",
      "stageName": "'"${STAGE_NAME}"'",
      "branchName": "'"${BRANCH_NAME:-unknown}"'",
      "commitId": "'"${COMMIT_ID:-unknown}"'",
      "operator": "'"${OPERATOR}"'",
      "exitCode": '"${exit_code}"',
      "logTail": "'"${log_tail}"'"
    }' || true
  echo ""
  exit "${exit_code}"
}
trap on_error ERR

run_stage() {
  STAGE_NAME="$1"
  shift
  echo ""
  echo "===== ${STAGE_NAME} ====="
  "$@"
}

adapter_preview() {
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
}

adapter_audit_preview() {
  local audit_json
  audit_json=$(curl -sS \
    -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
    "${BASE_URL}/adapter/audit/${TASK_ID}")
  echo "${audit_json}"
  echo "${audit_json}" | grep -q '"event"[[:space:]]*:[[:space:]]*"preview"'
  echo "${audit_json}" | grep -q '"status"[[:space:]]*:[[:space:]]*"PREVIEWED"'
}

adapter_execute() {
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
}

adapter_status() {
  local status_json
  status_json=$(curl -sS \
    -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
    "${BASE_URL}/adapter/status/${TASK_ID}")
  echo "${status_json}"
  echo "${status_json}" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCESS"'
}

adapter_final_audit() {
  local audit_json
  audit_json=$(curl -sS \
    -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
    "${BASE_URL}/adapter/audit/${TASK_ID}")
  echo "${audit_json}"
  echo "${audit_json}" | grep -q '"event"[[:space:]]*:[[:space:]]*"preview"'
  echo "${audit_json}" | grep -q '"event"[[:space:]]*:[[:space:]]*"execute"'
  echo "${audit_json}" | grep -q '"event"[[:space:]]*:[[:space:]]*"status"'
  echo "${audit_json}" | grep -q '"status"[[:space:]]*:[[:space:]]*"SUCCESS"'
}

if [ "${DELIVERY_MODE}" != "release" ]; then
  echo "yunxiao_release_main.sh can only run with DELIVERY_MODE=release" >&2
  exit 1
fi

echo "DELIVERY_MODE=${DELIVERY_MODE}"
echo "REQUIREMENT_ID=${REQUIREMENT_ID}"
echo "TASK_ID=${TASK_ID}"
echo "YUNXIAO_APPROVAL_ID=${YUNXIAO_APPROVAL_ID}"
echo "LOG_FILE=${LOG_FILE}"

run_stage "Adapter Preview" adapter_preview
run_stage "Adapter Audit Preview" adapter_audit_preview
run_stage "Adapter Execute" adapter_execute
run_stage "Adapter Status" adapter_status
run_stage "Adapter Final Audit" adapter_final_audit

trap - ERR
STAGE_NAME="completed"
echo ""
echo "Adapter release main completed: TASK_ID=${TASK_ID}"
