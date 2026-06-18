import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.apifox import maybe_import_from_flow_event  # noqa: E402


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
        ), patch("app.apifox._import_openapi") as import_openapi:
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


if __name__ == "__main__":
    unittest.main()
