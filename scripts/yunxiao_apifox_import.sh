#!/usr/bin/env bash
set -euo pipefail

: "${APIFOX_ACCESS_TOKEN:?APIFOX_ACCESS_TOKEN is required}"
: "${APIFOX_PROJECT_ID:?APIFOX_PROJECT_ID is required}"
: "${OPENAPI_URL:?OPENAPI_URL is required, must be direct json/yaml url}"

APIFOX_BASE_URL="${APIFOX_BASE_URL:-https://api.apifox.com}"
APIFOX_API_VERSION="${APIFOX_API_VERSION:-2024-03-28}"
APIFOX_LOCALE="${APIFOX_LOCALE:-zh-CN}"
ENDPOINT_OVERWRITE_BEHAVIOR="${APIFOX_ENDPOINT_OVERWRITE_BEHAVIOR:-OVERWRITE_EXISTING}"
SCHEMA_OVERWRITE_BEHAVIOR="${APIFOX_SCHEMA_OVERWRITE_BEHAVIOR:-KEEP_EXISTING}"

if [ "${RELEASE_RESULT:-SUCCESS}" != "SUCCESS" ]; then
  echo "Skip Apifox import: RELEASE_RESULT=${RELEASE_RESULT:-unknown}"
  exit 0
fi

echo "Apifox project=${APIFOX_PROJECT_ID}"
echo "OpenAPI url=${OPENAPI_URL}"

target_endpoint_folder=''
if [ -n "${APIFOX_TARGET_ENDPOINT_FOLDER_ID:-}" ]; then
  target_endpoint_folder=',"targetEndpointFolderId":'"${APIFOX_TARGET_ENDPOINT_FOLDER_ID}"
fi

target_schema_folder=''
if [ -n "${APIFOX_TARGET_SCHEMA_FOLDER_ID:-}" ]; then
  target_schema_folder=',"targetSchemaFolderId":'"${APIFOX_TARGET_SCHEMA_FOLDER_ID}"
fi

payload=$(cat <<JSON
{
  "input": {
    "url": "${OPENAPI_URL}"
  },
  "options": {
    "endpointOverwriteBehavior": "${ENDPOINT_OVERWRITE_BEHAVIOR}",
    "schemaOverwriteBehavior": "${SCHEMA_OVERWRITE_BEHAVIOR}",
    "updateFolderOfChangedEndpoint": true,
    "prependBasePath": true
    ${target_endpoint_folder}
    ${target_schema_folder}
  }
}
JSON
)

curl -sS --location --globoff \
  "${APIFOX_BASE_URL}/v1/projects/${APIFOX_PROJECT_ID}/import-openapi?locale=${APIFOX_LOCALE}" \
  --header "X-Apifox-Api-Version: ${APIFOX_API_VERSION}" \
  --header "Authorization: Bearer ${APIFOX_ACCESS_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "${payload}"

echo ""
