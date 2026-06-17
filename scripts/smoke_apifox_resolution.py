"""
Smoke-test Adapter Apifox project resolution without calling Apifox.

This covers the current Yunxiao webhook shape: the payload only contains
task/sources/globalParams, does not pass a project in URL/query params, and the
Adapter resolves the project from APIFOX_PIPELINE_<PIPELINE_ID>_PROJECT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.apifox import maybe_import_from_flow_event  # noqa: E402


def main() -> None:
    original_env = os.environ.copy()
    try:
        os.environ.update(
            {
                "APIFOX_AUTO_IMPORT": "false",
                "APIFOX_PIPELINE_4437990_PROJECT": "jdb-order",
                "APIFOX_PROJECT_JDB_ORDER_ID": "7049238",
                "APIFOX_OPENAPI_URL_TEMPLATE": "https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs",
            }
        )
        payload = {
            "task": {
                "pipelineId": "4437990",
                "buildNumber": "1259",
                "statusCode": "SUCCESS",
                "stageName": "Release",
                "taskName": "Adapter Apifox Import",
            },
            "sources": [
                {
                    "repo": "test.git",
                    "branchName": "master",
                    "commitId": "smoke",
                }
            ],
            "globalParams": [],
        }
        result = maybe_import_from_flow_event(payload)
        assert result["enabled"] is False, result
        assert result["imported"] is False, result
        assert result["projectName"] == "jdb-order", result
        assert result["projectNameSource"] == "environment_pipeline", result
        assert result["projectKey"] == "JDB_ORDER", result
        assert result["projectId"] == "7049238", result
        assert result["openapiUrl"] == "http://47.116.102.238:18080/adapter/openapi/jdb-order", result
        assert result["upstreamOpenapiUrl"] == "https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs", result
        assert result["stripProjectPath"] is True, result
        print("apifox resolution smoke OK: pipelineId=4437990 -> jdb-order -> 7049238")
    finally:
        os.environ.clear()
        os.environ.update(original_env)


if __name__ == "__main__":
    main()
