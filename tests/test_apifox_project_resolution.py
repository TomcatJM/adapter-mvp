import json
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.apifox import fetch_sanitized_openapi, maybe_import_from_flow_event, verify_signed_upstream_url  # noqa: E402


class ApifoxProjectResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = os.environ.copy()
        os.environ.clear()
        os.environ.update(
            {
                "APIFOX_AUTO_IMPORT": "true",
                "APIFOX_ACCESS_TOKEN": "token-for-test",
                "APIFOX_DEFAULT_PROJECT_ID": "should-not-be-used",
                "OPENAPI_URL": "http://example.test/openapi.json",
                "APIFOX_STRIP_PROJECT_PATH": "false",
            }
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_missing_project_mapping_does_not_use_default_project_id(self) -> None:
        payload = {
            "task": {"pipelineId": "8460173", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [],
        }

        with patch("app.apifox._find_pipeline_config", return_value=None), patch(
            "app.apifox._find_project_config", return_value=None
        ), patch("app.apifox.discover_project_from_pipeline", return_value={"matched": False}), patch(
            "app.apifox._import_openapi"
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        import_openapi.assert_not_called()
        self.assertTrue(result["enabled"])
        self.assertFalse(result["imported"])
        self.assertIsNone(result["projectName"])
        self.assertEqual(result["projectNameSource"], "unresolved")
        self.assertIsNone(result["projectId"])
        self.assertEqual(result["projectConfigSource"], "unresolved")
        self.assertIn("missing Apifox project mapping", result["reason"])
        self.assertIn("APIFOX_DEFAULT_PROJECT_ID is intentionally ignored", result["reason"])

    def test_pipeline_id_can_auto_discover_project_and_use_cached_mapping(self) -> None:
        payload = {
            "task": {"pipelineId": "4836717", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://47.116.102.238:18080/openapi.json",
            "remark": "adapter-mvp self openapi",
        }

        with patch("app.apifox._find_pipeline_config") as find_pipeline_config, patch(
            "app.apifox.discover_project_from_pipeline",
            return_value={
                "matched": True,
                "projectName": "adapter-mvp",
                "apifoxProjectConfigId": 9,
                "source": "yunxiao_pipeline",
                "remark": "auto-discovered",
                "pipelineName": "adapter-mvp开发/UAT部署",
                "serviceName": "adapter-mvp",
                "envName": "dev-uat",
            },
        ) as discover, patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._find_project_config_by_id", return_value=project_config
        ), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 20}
        ), patch("app.apifox._import_openapi", return_value={"statusCode": 201}) as import_openapi:
            find_pipeline_config.side_effect = [
                None,
                {
                    "pipelineId": "4836717",
                    "apifoxProjectConfigId": 9,
                    "serviceName": "adapter-mvp",
                    "envName": "dev-uat",
                    "remark": "auto-discovered",
                },
            ]
            result = maybe_import_from_flow_event(payload)

        discover.assert_called_once_with("4836717")
        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["projectName"], "adapter-mvp")
        self.assertEqual(result["projectNameSource"], "database_pipeline_config_id")
        self.assertEqual(result["projectId"], "8460173")
        self.assertEqual(result["pipelineDiscovery"]["source"], "yunxiao_pipeline")

    def test_pipeline_mapping_uses_apifox_project_config_id_without_project_name_lookup(self) -> None:
        payload = {
            "task": {"pipelineId": "4537737", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [],
        }
        project_config = {
            "projectName": "pay-支付服务",
            "apifoxProjectId": "7857001",
            "openapiUrl": "https://micro-api-test.kidcastle.com.cn/gw/jdb-pay/v3/api-docs",
            "remark": "Apifox jdb团队项目初始化",
        }

        with patch(
            "app.apifox._find_pipeline_config",
            return_value={
                "pipelineId": "4537737",
                "pipelineName": "jdb-pay开发/UAT部署",
                "serviceName": "jdb-pay",
                "apifoxProjectConfigId": 23,
                "remark": "支付服务开发流水线",
            },
        ), patch("app.apifox._find_project_config") as find_project_config, patch(
            "app.apifox._find_project_config_by_id",
            return_value=project_config,
            create=True,
        ) as find_project_config_by_id, patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 8}
        ), patch("app.apifox._import_openapi", return_value={"statusCode": 201}) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        find_project_config.assert_not_called()
        find_project_config_by_id.assert_called_once_with(23)
        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["projectName"], "pay-支付服务")
        self.assertEqual(result["projectNameSource"], "database_pipeline_config_id")
        self.assertEqual(result["projectId"], "7857001")

    def test_missing_project_id_reports_project_name_without_default_fallback(self) -> None:
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }

        with patch("app.apifox._find_project_config", return_value=None), patch(
            "app.apifox._import_openapi"
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        import_openapi.assert_not_called()
        self.assertTrue(result["enabled"])
        self.assertFalse(result["imported"])
        self.assertEqual(result["projectName"], "adapter-mvp")
        self.assertEqual(result["projectNameSource"], "payload")
        self.assertIsNone(result["projectId"])
        self.assertEqual(result["projectConfigSource"], "unresolved")
        self.assertIn("missing Apifox project ID for projectName=adapter-mvp", result["reason"])
        self.assertIn("APIFOX_PROJECT_ADAPTER_MVP_ID", result["reason"])

    def test_db_project_config_can_provide_project_specific_openapi_url(self) -> None:
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
            "remark": "adapter-mvp on server 40",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ), patch("app.apifox._import_openapi", return_value={"statusCode": 201}) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["projectId"], "8460173")
        self.assertEqual(result["projectConfigSource"], "database")
        self.assertEqual(result["upstreamOpenapiUrl"], "http://40.example.test:18080/openapi.json")

    def test_db_project_account_token_overrides_environment_token(self) -> None:
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "accountName": "apifox-main",
            "accessToken": "db-token-for-test",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ), patch("app.apifox._import_openapi", return_value={"statusCode": 201}) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["accessTokenSource"], "database_account")
        self.assertNotIn("accessToken", result)
        self.assertEqual(import_openapi.call_args.args[0]["accessToken"], "db-token-for-test")

    def test_waits_before_import_when_apifox_import_delay_is_configured(self) -> None:
        os.environ["APIFOX_IMPORT_DELAY_SECONDS"] = "180"
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ), patch("app.apifox.time.sleep") as sleep, patch(
            "app.apifox._import_openapi", return_value={"statusCode": 201}
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        sleep.assert_called_once_with(180)
        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["importDelaySeconds"], 180)

    def test_db_project_config_import_delay_overrides_environment_delay(self) -> None:
        os.environ["APIFOX_IMPORT_DELAY_SECONDS"] = "30"
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
            "importDelaySeconds": 180,
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ), patch("app.apifox.time.sleep") as sleep, patch(
            "app.apifox._import_openapi", return_value={"statusCode": 201}
        ):
            result = maybe_import_from_flow_event(payload)

        sleep.assert_called_once_with(180)
        self.assertTrue(result["imported"])
        self.assertEqual(result["importDelaySeconds"], 180)

    def test_does_not_wait_when_apifox_import_delay_is_not_configured(self) -> None:
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ), patch("app.apifox.time.sleep") as sleep, patch(
            "app.apifox._import_openapi", return_value={"statusCode": 201}
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        sleep.assert_not_called()
        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["importDelaySeconds"], 0)

    def test_missing_apifox_token_reports_account_config_hint(self) -> None:
        os.environ.pop("APIFOX_ACCESS_TOKEN", None)
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [{"key": "PROJECT_NAME", "value": "adapter-mvp"}],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._import_openapi"
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        import_openapi.assert_not_called()
        self.assertFalse(result["imported"])
        self.assertEqual(result["accessTokenSource"], "unresolved")
        self.assertIn("adapter_apifox_account_config", result["reason"])

    def test_payload_openapi_url_overrides_db_project_openapi_url(self) -> None:
        os.environ["ADAPTER_API_TOKEN"] = "adapter-token-for-signing"
        os.environ["ADAPTER_PUBLIC_BASE_URL"] = "http://adapter.example.test"
        os.environ["APIFOX_STRIP_PROJECT_PATH"] = "true"
        payload = {
            "task": {"pipelineId": "4437990", "statusCode": "SUCCESS"},
            "sources": [],
            "globalParams": [
                {"key": "PROJECT_NAME", "value": "adapter-mvp"},
                {"key": "OPENAPI_URL", "value": "http://payload.example.test/openapi.json"},
            ],
        }
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
            "remark": "adapter-mvp on server 40",
        }

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox._preflight_openapi", return_value={"ok": True, "pathCount": 1}
        ) as preflight_openapi, patch(
            "app.apifox._import_openapi", return_value={"statusCode": 201}
        ) as import_openapi:
            result = maybe_import_from_flow_event(payload)

        preflight_openapi.assert_called_once_with("adapter-mvp", "http://payload.example.test/openapi.json")
        import_openapi.assert_called_once()
        self.assertTrue(result["imported"])
        self.assertEqual(result["upstreamOpenapiUrl"], "http://payload.example.test/openapi.json")
        parsed = urlparse(result["openapiUrl"])
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "http://adapter.example.test/adapter/openapi/adapter-mvp")
        query = parse_qs(parsed.query)
        self.assertEqual(query["upstreamUrl"][0], "http://payload.example.test/openapi.json")
        self.assertEqual(
            verify_signed_upstream_url("adapter-mvp", query["upstreamUrl"][0], query["signature"][0]),
            "http://payload.example.test/openapi.json",
        )

    def test_fetch_sanitized_openapi_uses_db_project_openapi_url(self) -> None:
        project_config = {
            "projectName": "adapter-mvp",
            "apifoxProjectId": "8460173",
            "openapiUrl": "http://40.example.test:18080/openapi.json",
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(
                    {
                        "openapi": "3.0.1",
                        "info": {"title": "Adapter MVP", "version": "1.0.0"},
                        "paths": {"/adapter-mvp/health": {"get": {"summary": "health"}}},
                    }
                ).encode("utf-8")

        with patch("app.apifox._find_project_config", return_value=project_config), patch(
            "app.apifox.urllib.request.urlopen", return_value=FakeResponse()
        ) as urlopen:
            result = fetch_sanitized_openapi("adapter-mvp")

        urlopen.assert_called_once()
        self.assertEqual(urlopen.call_args.args[0], "http://40.example.test:18080/openapi.json")
        self.assertIn("/health", result["paths"])


if __name__ == "__main__":
    unittest.main()
