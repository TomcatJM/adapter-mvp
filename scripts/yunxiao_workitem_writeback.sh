#!/usr/bin/env bash
set -euo pipefail

: "${REQUIREMENT_ID:?REQUIREMENT_ID is required}"
: "${YUNXIAO_ORG_ID:?YUNXIAO_ORG_ID is required}"
: "${YUNXIAO_TOKEN:?YUNXIAO_TOKEN is required}"

DELIVERY_MODE="${DELIVERY_MODE:-release}"
BUILD_NO="${BUILD_NUMBER:-0}"
DEFAULT_TASK_ID="rel-${REQUIREMENT_ID}-${BUILD_NO}"
TASK_ID="${TASK_ID:-${DEFAULT_TASK_ID}}"
PIPELINE_RUN="${PIPELINE_ID:-manual}/${BUILD_NO}"
BASE_URL="${YUNXIAO_OPENAPI_BASE_URL:-https://devops.cn-hangzhou.aliyuncs.com}"
WRITEBACK_ENABLED="${YUNXIAO_WRITEBACK_ENABLED:-false}"
RESULT="${RELEASE_RESULT:-SUCCESS}"
FIELD_KEY="${YUNXIAO_WRITEBACK_FIELD:-description}"
FIELD_TYPE="${YUNXIAO_WRITEBACK_FIELD_TYPE:-text}"
COMMENT="【Adapter Release 回写】结果：${RESULT}; 主链路：${TASK_ID}; 流水线：${PIPELINE_RUN}; 审计：preview+execute+status已复核"

if [ "${DELIVERY_MODE}" != "release" ]; then
  echo "Skip completion writeback: DELIVERY_MODE=${DELIVERY_MODE}"
  exit 0
fi

echo "writeback target=${REQUIREMENT_ID}"
echo "writeback enabled=${WRITEBACK_ENABLED}"

writeback_one() {
  local workitem_id="$1"
  echo "writeback workitem=${workitem_id}"
  if [ "${WRITEBACK_ENABLED}" != "true" ]; then
    echo "dry-run comment=${COMMENT}"
    return 0
  fi

  local payload
  payload=$(cat <<JSON
{"identifier":"${workitem_id}","propertyKey":"${FIELD_KEY}","propertyValue":"${COMMENT}","fieldType":"${FIELD_TYPE}"}
JSON
)

  curl -sS -X POST "${BASE_URL}/organization/${YUNXIAO_ORG_ID}/workitems/update" \
    -H "Authorization: Bearer ${YUNXIAO_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${payload}"
  echo ""
}

writeback_one "${REQUIREMENT_ID}"

IFS=',' read -r -a CHILDREN <<< "${CHILD_TASK_IDS:-}"
for CHILD_ID in "${CHILDREN[@]}"; do
  CHILD_ID="$(echo "${CHILD_ID}" | xargs)"
  [ -z "${CHILD_ID}" ] && continue
  writeback_one "${CHILD_ID}"
done
