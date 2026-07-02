#!/usr/bin/env bash
set -Eeuo pipefail

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "${name} is required" >&2
    exit 1
  fi
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "${name} command is required" >&2
    exit 1
  fi
}

trim_slashes() {
  local value="$1"
  value="${value#/}"
  value="${value%/}"
  printf '%s' "${value}"
}

sha256_file() {
  local file="$1"
  local output="$2"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file}" >"${output}"
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file}" >"${output}"
    return
  fi
  echo "sha256sum or shasum command is required" >&2
  exit 1
}

require_env PROJECT_KEY
require_env BRANCH_NAME
require_env COMMIT_ID
require_env OSS_BUCKET
require_env OSS_PREFIX
require_env ADAPTER_BASE_URL
require_env ADAPTER_API_TOKEN

DRY_RUN="${DRY_RUN:-false}"
CODEGRAPH_BIN="${CODEGRAPH_BIN:-codegraph}"
OSSUTIL_BIN="${OSSUTIL_BIN:-ossutil}"
CURL_BIN="${CURL_BIN:-curl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WORK_DIR_INPUT="${WORK_DIR:-.}"
WORK_DIR="$(cd "${WORK_DIR_INPUT}" && pwd)"
OUTPUT_DIR_INPUT="${OUTPUT_DIR:-${WORK_DIR}/codegraph-artifacts}"
mkdir -p "${OUTPUT_DIR_INPUT}"
OUTPUT_DIR="$(cd "${OUTPUT_DIR_INPUT}" && pwd)"
INDEX_VERSION="${INDEX_VERSION:-${COMMIT_ID}}"
STORAGE_TYPE="${STORAGE_TYPE:-oss}"
INDEX_STATUS="${INDEX_STATUS:-success}"

OSS_PREFIX_CLEAN="$(trim_slashes "${OSS_PREFIX}")"
OBJECT_PREFIX="${OSS_PREFIX_CLEAN}/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}"
OSS_DEST="oss://${OSS_BUCKET}/${OBJECT_PREFIX}/"
INDEX_ARCHIVE="${OUTPUT_DIR}/codegraph-index.tar.gz"
STATUS_JSON="${OUTPUT_DIR}/codegraph-status.json"
SHA256_TXT="${OUTPUT_DIR}/sha256.txt"
CALLBACK_URL="${ADAPTER_BASE_URL%/}/adapter/codegraph/index-callback"
export PROJECT_KEY BRANCH_NAME COMMIT_ID OSS_BUCKET OBJECT_PREFIX INDEX_VERSION STORAGE_TYPE INDEX_STATUS STATUS_JSON

echo "PROJECT_KEY=${PROJECT_KEY}"
echo "BRANCH_NAME=${BRANCH_NAME}"
echo "COMMIT_ID=${COMMIT_ID}"
echo "INDEX_VERSION=${INDEX_VERSION}"
echo "OSS_DEST=${OSS_DEST}"
echo "CALLBACK_URL=${CALLBACK_URL}"
echo "DRY_RUN=${DRY_RUN}"

if [ "${DRY_RUN}" = "true" ]; then
  echo "Dry run only; skip codegraph, ossutil, and Adapter callback."
  echo "Would create: ${INDEX_ARCHIVE}"
  echo "Would create: ${STATUS_JSON}"
  echo "Would create: ${SHA256_TXT}"
  echo "Would upload to: ${OSS_DEST}"
  echo "Would callback: ${CALLBACK_URL}"
  exit 0
fi

require_command "${CODEGRAPH_BIN}"
require_command "${OSSUTIL_BIN}"
require_command "${CURL_BIN}"
require_command "${PYTHON_BIN}"

(
  cd "${WORK_DIR}"
  "${CODEGRAPH_BIN}" telemetry off
  if [ -d ".codegraph" ]; then
    "${CODEGRAPH_BIN}" index .
  else
    "${CODEGRAPH_BIN}" init .
  fi
  "${CODEGRAPH_BIN}" status . --json >"${STATUS_JSON}"
  tar -czf "${INDEX_ARCHIVE}" .codegraph -C "${OUTPUT_DIR}" codegraph-status.json
)

sha256_file "${INDEX_ARCHIVE}" "${SHA256_TXT}"

"${OSSUTIL_BIN}" cp "${INDEX_ARCHIVE}" "${OSS_DEST}"
"${OSSUTIL_BIN}" cp "${STATUS_JSON}" "${OSS_DEST}"
"${OSSUTIL_BIN}" cp "${SHA256_TXT}" "${OSS_DEST}"

PAYLOAD_FILE="${OUTPUT_DIR}/codegraph-index-callback.json"
"${PYTHON_BIN}" - "${PAYLOAD_FILE}" <<'PY'
import json
import os
import sys
from pathlib import Path

payload_path = Path(sys.argv[1])
status_path = Path(os.environ["STATUS_JSON"])
stats = {}
try:
    raw_status = json.loads(status_path.read_text(encoding="utf-8"))
    for key in ("files", "nodes", "edges"):
        if key in raw_status:
            stats[key] = raw_status[key]
except Exception:
    stats = {}

object_prefix = os.environ["OBJECT_PREFIX"]
payload = {
    "projectKey": os.environ["PROJECT_KEY"],
    "branchName": os.environ["BRANCH_NAME"],
    "commitId": os.environ["COMMIT_ID"],
    "indexVersion": os.environ["INDEX_VERSION"],
    "storageType": os.environ["STORAGE_TYPE"],
    "bucketName": os.environ["OSS_BUCKET"],
    "objectKey": f"{object_prefix}/codegraph-index.tar.gz",
    "statusObjectKey": f"{object_prefix}/codegraph-status.json",
    "sha256ObjectKey": f"{object_prefix}/sha256.txt",
    "indexStatus": os.environ["INDEX_STATUS"],
    "stats": stats,
}
payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
PY

"${CURL_BIN}" -sS -X POST "${CALLBACK_URL}" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "@${PAYLOAD_FILE}"
echo ""

echo "CodeGraph index uploaded and callback sent: projectKey=${PROJECT_KEY}, commitId=${COMMIT_ID}"
