"""
Smoke-test Apifox project resolution from database configuration.

The script monkey-patches the DB lookup so it does not need a real database.
It verifies that PROJECT_NAME=jdb-order can resolve projectId=7049238 from
the project configuration table, and pipelineId=4989239 can resolve the
Apifox project through apifox_project_config_id.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.apifox as apifox  # noqa: E402


def main() -> None:
    original_env = os.environ.copy()
    original_lookup = getattr(apifox, "_find_project_config", None)
    original_lookup_by_id = getattr(apifox, "_find_project_config_by_id", None)
    original_pipeline_lookup = getattr(apifox, "_find_pipeline_config", None)
    try:
        os.environ.clear()
        os.environ.update(
            {
                "APIFOX_AUTO_IMPORT": "false",
                "APIFOX_OPENAPI_URL_TEMPLATE": "https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs",
            }
        )

        def fake_lookup(project_name: str):
            if project_name == "jdb-order":
                return {"apifoxProjectId": "7049238", "remark": "订单服务接口项目-流水线重新导入目标"}
            if project_name == "jdb-school-gmc":
                return {"apifoxProjectId": "8336358", "remark": "集团管理中心接口项目"}
            return None

        def fake_lookup_by_id(config_id: int):
            if config_id == 12:
                return {
                    "projectName": "jdb-school-gmc",
                    "apifoxProjectId": "8336358",
                    "remark": "集团管理中心接口项目",
                }
            return None

        def fake_pipeline_lookup(pipeline_id: str):
            if pipeline_id == "4989239":
                return {
                    "apifoxProjectConfigId": 12,
                    "pipelineName": "jdb-school-gmc开发/UAT部署",
                    "serviceName": "jdb-school-gmc",
                    "envName": "dev-uat",
                    "remark": "GMC Kubernetes发布流水线",
                }
            return None

        apifox._find_project_config = fake_lookup  # type: ignore[attr-defined]
        apifox._find_project_config_by_id = fake_lookup_by_id  # type: ignore[attr-defined]
        apifox._find_pipeline_config = fake_pipeline_lookup  # type: ignore[attr-defined]

        project_result = apifox.maybe_import_from_flow_event(
            {
                "task": {"pipelineId": "4437990", "buildNumber": "db-smoke", "statusCode": "SUCCESS"},
                "sources": [{"repo": "test.git"}],
                "globalParams": [{"key": "PROJECT_NAME", "value": "jdb-order"}],
            }
        )
        assert project_result["projectName"] == "jdb-order", project_result
        assert project_result["projectNameSource"] == "payload", project_result
        assert project_result["projectKey"] == "JDB_ORDER", project_result
        assert project_result["projectId"] == "7049238", project_result
        assert project_result["projectConfigSource"] == "database", project_result
        assert project_result["projectRemark"] == "订单服务接口项目-流水线重新导入目标", project_result
        assert project_result["openapiUrl"] == "http://47.116.102.238:18080/adapter/openapi/jdb-order", project_result
        assert project_result["upstreamOpenapiUrl"] == "https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs", project_result
        assert project_result["stripProjectPath"] is True, project_result

        pipeline_result = apifox.maybe_import_from_flow_event(
            {
                "task": {"pipelineId": "4989239", "buildNumber": "pipeline-db-smoke", "statusCode": "SUCCESS"},
                "sources": [],
                "globalParams": [],
            }
        )
        assert pipeline_result["projectName"] == "jdb-school-gmc", pipeline_result
        assert pipeline_result["projectNameSource"] == "database_pipeline_config_id", pipeline_result
        assert pipeline_result["projectNameRemark"] == "GMC Kubernetes发布流水线", pipeline_result
        assert pipeline_result["projectKey"] == "JDB_SCHOOL_GMC", pipeline_result
        assert pipeline_result["projectId"] == "8336358", pipeline_result
        assert pipeline_result["projectConfigSource"] == "database", pipeline_result
        assert pipeline_result["projectRemark"] == "集团管理中心接口项目", pipeline_result
        assert pipeline_result["openapiUrl"] == "http://47.116.102.238:18080/adapter/openapi/jdb-school-gmc", pipeline_result
        assert pipeline_result["upstreamOpenapiUrl"] == "https://micro-api-test.kidcastle.com.cn/gw/jdb-school-gmc/v3/api-docs", pipeline_result
        assert pipeline_result["stripProjectPath"] is True, pipeline_result
        print("apifox db config smoke OK: PROJECT_NAME=jdb-order and pipelineId=4989239 -> jdb-school-gmc -> projectId=8336358")
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        if original_lookup is None:
            try:
                delattr(apifox, "_find_project_config")
            except AttributeError:
                pass
        else:
            apifox._find_project_config = original_lookup  # type: ignore[attr-defined]
        if original_lookup_by_id is None:
            try:
                delattr(apifox, "_find_project_config_by_id")
            except AttributeError:
                pass
        else:
            apifox._find_project_config_by_id = original_lookup_by_id  # type: ignore[attr-defined]
        if original_pipeline_lookup is None:
            try:
                delattr(apifox, "_find_pipeline_config")
            except AttributeError:
                pass
        else:
            apifox._find_pipeline_config = original_pipeline_lookup  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
