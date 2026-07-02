import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.codegraph import handle_index_callback
from app.models import CodeGraphIndexCallbackRequest


class CodeGraphIndexCallbackTest(unittest.TestCase):
    def _request(self, **overrides) -> CodeGraphIndexCallbackRequest:
        payload = {
            "projectKey": "jdb-school-crm",
            "branchName": "develop",
            "commitId": "abc123",
            "indexVersion": "abc123-20260702",
            "storageType": "oss",
            "bucketName": "ai-dev-artifacts",
            "objectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
            "statusObjectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
            "sha256ObjectKey": "codegraph/jdb-school-crm/develop/abc123/sha256.txt",
            "indexStatus": "success",
            "stats": {"files": 1642, "nodes": 51655, "edges": 84017},
        }
        payload.update(overrides)
        return CodeGraphIndexCallbackRequest(**payload)

    def test_success_callback_records_index_version(self) -> None:
        project = {"projectKey": "jdb-school-crm", "projectName": "校CRM"}
        request = self._request()

        with patch("app.codegraph.db.find_adapter_project_config", return_value=project) as find_project, patch(
            "app.codegraph.db.upsert_codegraph_index"
        ) as upsert:
            result = handle_index_callback(request)

        find_project.assert_called_once_with("jdb-school-crm")
        upsert.assert_called_once_with(
            project_key="jdb-school-crm",
            branch_name="develop",
            commit_id="abc123",
            index_version="abc123-20260702",
            storage_type="oss",
            bucket_name="ai-dev-artifacts",
            object_key="codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
            status_object_key="codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
            sha256_object_key="codegraph/jdb-school-crm/develop/abc123/sha256.txt",
            index_status="success",
            stats={"files": 1642, "nodes": 51655, "edges": 84017},
            error_message=None,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["projectKey"], "jdb-school-crm")
        self.assertEqual(result["indexStatus"], "success")
        self.assertFalse(result["workflowAdvanced"])

    def test_failed_callback_records_error_message(self) -> None:
        request = self._request(indexStatus="failed", errorMessage="codegraph index failed")

        with patch("app.codegraph.db.find_adapter_project_config", return_value={"projectKey": "jdb-school-crm"}), patch(
            "app.codegraph.db.upsert_codegraph_index"
        ) as upsert:
            result = handle_index_callback(request)

        self.assertEqual(result["indexStatus"], "failed")
        self.assertEqual(upsert.call_args.kwargs["error_message"], "codegraph index failed")

    def test_missing_project_config_fails_explicitly(self) -> None:
        request = self._request()

        with patch("app.codegraph.db.find_adapter_project_config", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                handle_index_callback(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("adapter_project_config", raised.exception.detail)

    def test_callback_route_requires_api_token(self) -> None:
        from app import main

        route = next(route for route in main.app.routes if getattr(route, "path", None) == "/adapter/codegraph/index-callback")
        dependency_names = [dependency.call.__name__ for dependency in route.dependant.dependencies]

        self.assertIn("require_api_token", dependency_names)


if __name__ == "__main__":
    unittest.main()
