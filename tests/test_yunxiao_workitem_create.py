import os
import unittest
from unittest.mock import patch

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ModuleNotFoundError:
    HAS_PYDANTIC = False


ENV = {
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "ak-test",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret-test",
    "YUNXIAO_ORGANIZATION_ID": "org-1",
    "YUNXIAO_PROJECT_ID": "project-1",
    "YUNXIAO_WORKITEM_TYPE_IDENTIFIER": "type-req",
    "YUNXIAO_WORKITEM_ASSIGNEE": "account-1",
}


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class YunxiaoWorkitemCreateTest(unittest.TestCase):
    def test_create_workitem_builds_payload_and_sanitizes_description(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": "true", "workitemIdentifier": "YX-1", "requestId": "req-1"}

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = create_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["workitemIdentifier"], "YX-1")
        self.assertEqual(captured["path"], "/organization/org-1/workitem")
        self.assertEqual(captured["action"], "CreateWorkitemV2")
        payload = captured["payload"]
        self.assertEqual(payload["subject"], "新增客户跟进记录接口")
        self.assertEqual(payload["assignedTo"], "account-1")
        self.assertEqual(payload["spaceIdentifier"], "project-1")
        self.assertEqual(payload["category"], "Req")
        self.assertEqual(payload["workitemTypeIdentifier"], "type-req")
        self.assertIn("Workflow：wf-test-1", payload["description"])
        self.assertIn("POST /crm/client/follow-record", payload["description"])
        self.assertNotIn("secret-value", payload["description"])

    def test_create_workitem_error_response_is_not_treated_as_identifier(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        response = {
            "workitemIdentifier": {
                "path": "/open/api/cloud/v1/workitem/createV2",
                "error": "Internal Server Error",
                "message": "Openapi.Unauthorized.Failed",
                "status": 500,
            },
            "errorMessage": "",
        }

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", return_value=response
        ):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("Yunxiao create workitem failed", str(raised.exception))
        self.assertIn("Openapi.Unauthorized.Failed", str(raised.exception))

    def test_create_workitem_uses_db_project_and_account_config_before_env(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": True, "workitemIdentifier": "YX-DB-1", "requestId": "req-db-1"}

        with patch.dict(os.environ, {**ENV, "YUNXIAO_PROJECT_ID": "env-project"}, clear=True), patch(
            "app.yunxiao.db.configured", return_value=True
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "main-ak",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Task",
                "workitemTypeIdentifier": "type-db",
                "assignee": "account-db",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "main-ak",
                "accessKeyId": "ak-db",
                "accessKeySecret": "secret-db",
                "endpoint": "https://yunxiao.example.test",
            },
        ), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = create_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["workitemIdentifier"], "YX-DB-1")
        self.assertEqual(result["projectName"], "jdb-school-crm")
        self.assertEqual(result["projectId"], "project-db")
        self.assertEqual(result["configSource"], "db")
        self.assertEqual(captured["path"], "/organization/org-db/workitem")
        self.assertEqual(captured["config"]["accessKeyId"], "ak-db")
        self.assertEqual(captured["config"]["endpoint"], "yunxiao.example.test")
        payload = captured["payload"]
        self.assertEqual(payload["spaceIdentifier"], "project-db")
        self.assertEqual(payload["category"], "Task")
        self.assertEqual(payload["workitemTypeIdentifier"], "type-db")
        self.assertEqual(payload["assignedTo"], "account-db")
        self.assertEqual(result["assignee"]["source"], "project_config_default_assignee")

    def test_create_workitem_uses_legacy_token_db_account(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": True, "id": "YX-LEGACY-1"}

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "legacy-main",
                "organizationId": "org-legacy",
                "projectId": "project-legacy",
                "sprintId": "sprint-legacy",
                "category": "Req",
                "workitemTypeIdentifier": "type-legacy",
                "assignee": "account-legacy",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "legacy-main",
                "authType": "legacy_token",
                "legacyToken": "token-legacy",
                "endpoint": "https://openapi-rdc.aliyuncs.com",
            },
        ), patch(
            "app.yunxiao._request_yunxiao_legacy_openapi", side_effect=fake_request
        ) as legacy_request, patch(
            "app.yunxiao._request_yunxiao_openapi"
        ) as acs_request:
            result = create_yunxiao_workitem(workflow, "codex")

        legacy_request.assert_called_once()
        acs_request.assert_not_called()
        self.assertEqual(result["workitemIdentifier"], "YX-LEGACY-1")
        self.assertEqual(result["authType"], "legacy_token")
        self.assertEqual(captured["config"]["legacyToken"], "token-legacy")
        self.assertEqual(captured["payload"]["spaceIdentifier"], "project-legacy")
        self.assertEqual(captured["payload"]["sprint"], "sprint-legacy")

    def test_create_workitem_uses_personal_token_api(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": True, "identifier": "YX-PAT-1"}

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "pat-main",
                "organizationId": "org-pat",
                "projectId": "project-pat",
                "category": "Req",
                "workitemTypeIdentifier": "type-pat",
                "assignee": "account-pat",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "pat-main",
                "authType": "personal_token",
                "legacyToken": "pat-secret",
                "endpoint": "https://devops.cn-hangzhou.aliyuncs.com",
            },
        ), patch(
            "app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request
        ) as pat_request, patch(
            "app.yunxiao._request_yunxiao_openapi"
        ) as acs_request:
            result = create_yunxiao_workitem(workflow, "codex")

        pat_request.assert_called_once()
        acs_request.assert_not_called()
        self.assertEqual(result["workitemIdentifier"], "YX-PAT-1")
        self.assertEqual(result["authType"], "personal_token")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/oapi/v1/projex/organizations/org-pat/workitems")
        self.assertEqual(captured["payload"]["spaceId"], "project-pat")
        self.assertEqual(captured["payload"]["workitemTypeId"], "type-pat")
        self.assertNotIn("spaceIdentifier", captured["payload"])
        self.assertNotIn("workitemTypeIdentifier", captured["payload"])
        self.assertEqual(captured["config"]["personalToken"], "pat-secret")

    def test_create_workitem_uses_default_project_member_before_legacy_default_assignee(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": True, "workitemIdentifier": "YX-MEMBER-1", "requestId": "req-member-1"}

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "main-ak",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Req",
                "workitemTypeIdentifier": "type-db",
                "assignee": "legacy-default",
            },
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member",
            return_value={
                "projectName": "jdb-school-crm",
                "name": "姬志猛",
                "accountId": "user-jzm",
                "isDefault": True,
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "main-ak",
                "accessKeyId": "ak-db",
                "accessKeySecret": "secret-db",
                "endpoint": "devops.cn-hangzhou.aliyuncs.com",
            },
        ), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = create_yunxiao_workitem(workflow, "codex")

        self.assertEqual(captured["payload"]["assignedTo"], "user-jzm")
        self.assertEqual(result["assignee"]["name"], "姬志猛")
        self.assertEqual(result["assignee"]["accountId"], "user-jzm")
        self.assertEqual(result["assignee"]["source"], "project_member_default")

    def test_create_workitem_uses_requested_project_member(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"]["assigneeName"] = "张三"
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return {"success": True, "workitemIdentifier": "YX-MEMBER-2", "requestId": "req-member-2"}

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "main-ak",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Req",
                "workitemTypeIdentifier": "type-db",
                "assignee": "legacy-default",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member",
            return_value={
                "projectName": "jdb-school-crm",
                "name": "张三",
                "accountId": "user-zhangsan",
                "isDefault": False,
            },
        ) as find_member, patch(
            "app.yunxiao.db.find_default_yunxiao_project_member"
        ) as find_default, patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "main-ak",
                "accessKeyId": "ak-db",
                "accessKeySecret": "secret-db",
                "endpoint": "devops.cn-hangzhou.aliyuncs.com",
            },
        ), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = create_yunxiao_workitem(workflow, "codex")

        find_member.assert_called_once_with("jdb-school-crm", "张三")
        find_default.assert_not_called()
        self.assertEqual(captured["payload"]["assignedTo"], "user-zhangsan")
        self.assertEqual(result["assignee"]["source"], "project_member_requested")

    def test_requested_project_member_missing_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"]["assigneeName"] = "不存在的人"

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "main-ak",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Req",
                "workitemTypeIdentifier": "type-db",
                "assignee": "legacy-default",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "main-ak",
                "accessKeyId": "ak-db",
                "accessKeySecret": "secret-db",
            },
        ):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        self.assertIn("Yunxiao assignee config missing", str(raised.exception))
        self.assertIn("adapter_yunxiao_project_member", str(raised.exception))

    def test_create_workitem_resolves_multiple_projects_from_workflow_context(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        projects = {
            "jdb-school-crm": {
                "projectName": "jdb-school-crm",
                "accountName": "ak-a",
                "organizationId": "org-a",
                "projectId": "project-a",
                "category": "Req",
                "workitemTypeIdentifier": "type-a",
                "assignee": "user-a",
            },
            "jdb-school-gmc": {
                "projectName": "jdb-school-gmc",
                "accountName": "ak-b",
                "organizationId": "org-b",
                "projectId": "project-b",
                "category": "Req",
                "workitemTypeIdentifier": "type-b",
                "assignee": "user-b",
            },
        }
        accounts = {
            "ak-a": {"accountName": "ak-a", "accessKeyId": "id-a", "accessKeySecret": "secret-a"},
            "ak-b": {"accountName": "ak-b", "accessKeyId": "id-b", "accessKeySecret": "secret-b"},
        }
        captured: list[dict] = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            return {
                "success": True,
                "workitemIdentifier": f"YX-{len(captured)}",
                "requestId": f"req-{len(captured)}",
            }

        first = _workflow()
        second = _workflow()
        second["workflowId"] = "wf-test-2"
        second["context"] = {
            **second["context"],
            "projectName": "jdb-school-gmc",
            "requirement": {**second["context"]["requirement"], "affectedRepos": ["jdb-school-crm"]},
        }

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config", side_effect=lambda name: projects.get(name)
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config", side_effect=lambda name: accounts.get(name)
        ), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            first_result = create_yunxiao_workitem(first, "codex")
            second_result = create_yunxiao_workitem(second, "codex")

        self.assertEqual(first_result["projectName"], "jdb-school-crm")
        self.assertEqual(first_result["projectId"], "project-a")
        self.assertEqual(second_result["projectName"], "jdb-school-gmc")
        self.assertEqual(second_result["projectId"], "project-b")
        self.assertEqual(captured[0]["payload"]["spaceIdentifier"], "project-a")
        self.assertEqual(captured[1]["payload"]["spaceIdentifier"], "project-b")

    def test_missing_db_project_config_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config", return_value=None
        ):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("Yunxiao project config missing", str(raised.exception))
        self.assertIn("projectName=jdb-school-crm", str(raised.exception))
        self.assertIn("adapter_yunxiao_project_config", str(raised.exception))

    def test_missing_db_account_config_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "missing-ak",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Req",
                "workitemTypeIdentifier": "type-db",
                "assignee": "account-db",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch("app.yunxiao.db.find_yunxiao_account_config", return_value=None):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("Yunxiao account config missing", str(raised.exception))
        self.assertIn("accountName=missing-ak", str(raised.exception))
        self.assertIn("adapter_yunxiao_account_config", str(raised.exception))

    def test_missing_legacy_token_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        with patch.dict(os.environ, {}, clear=True), patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config",
            return_value={
                "projectName": "jdb-school-crm",
                "accountName": "legacy-main",
                "organizationId": "org-db",
                "projectId": "project-db",
                "category": "Req",
                "workitemTypeIdentifier": "type-db",
                "assignee": "account-db",
            },
        ), patch(
            "app.yunxiao.db.find_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member", return_value=None
        ), patch(
            "app.yunxiao.db.find_yunxiao_account_config",
            return_value={
                "accountName": "legacy-main",
                "authType": "legacy_token",
                "endpoint": "https://openapi-rdc.aliyuncs.com",
            },
        ):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("adapter_yunxiao_account_config.legacy_token", str(raised.exception))
        self.assertIn("legacy token auth is enabled", str(raised.exception))

    def test_missing_config_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("Yunxiao config missing", str(raised.exception))
        self.assertIn("ALIBABA_CLOUD_ACCESS_KEY_ID", str(raised.exception))
        self.assertIn("YUNXIAO_PROJECT_ID", str(raised.exception))

    def test_advance_requirement_parsed_creates_workitem_and_requests_coding(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = _workflow()
        created_workflow = {**workflow, "status": "YUNXIAO_TASK_CREATED", "yunxiaoTaskId": "YX-1"}
        captured = {}

        def fake_created(**kwargs):
            captured["created"] = kwargs
            return {**created_workflow, "context": kwargs["context"]}

        def fake_coding(**kwargs):
            captured["coding"] = kwargs
            return {**created_workflow, "status": "CODING_REQUESTED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.create_yunxiao_workitem",
            return_value={
                "workitemIdentifier": "YX-1",
                "requestId": "req-1",
                "projectId": "project-1",
                "category": "Req",
                "workitemTypeIdentifier": "type-req",
                "title": "新增客户跟进记录接口",
            },
        ), patch("app.workflow.db.update_workflow_yunxiao_task_created", side_effect=fake_created), patch(
            "app.workflow.db.update_workflow_coding_requested", side_effect=fake_coding
        ):
            result = advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertTrue(result["advanced"])
        self.assertEqual(result["workflow"]["status"], "CODING_REQUESTED")
        self.assertEqual(result["workflow"]["yunxiaoTaskId"], "YX-1")
        self.assertEqual(captured["created"]["from_status"], "REQUIREMENT_PARSED")
        self.assertEqual(captured["created"]["yunxiao_task_id"], "YX-1")
        self.assertEqual(captured["coding"]["event_payload"]["yunxiaoTaskId"], "YX-1")

    def test_advance_requirement_parsed_with_existing_workitem_skips_creation(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = {**_workflow(), "yunxiaoTaskId": "YX-1"}
        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.create_yunxiao_workitem"
        ) as create_workitem:
            result = advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        create_workitem.assert_not_called()
        self.assertFalse(result["advanced"])
        self.assertTrue(result["existing"])
        self.assertEqual(result["workflow"]["yunxiaoTaskId"], "YX-1")

    def test_advance_requirement_parsed_records_create_failure_without_advancing(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import WorkflowError, advance_workflow
        from app.yunxiao import YunxiaoError

        workflow = _workflow()
        captured = {}

        def fake_record(**kwargs):
            captured.update(kwargs)
            return {**workflow, "lastError": kwargs["error"], "retryCount": 1}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.create_yunxiao_workitem", side_effect=YunxiaoError("Yunxiao config missing: YUNXIAO_PROJECT_ID")
        ), patch("app.workflow.db.record_workflow_error", side_effect=fake_record):
            with self.assertRaises(WorkflowError):
                advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertEqual(captured["status"], "REQUIREMENT_PARSED")
        self.assertEqual(captured["event_type"], "yunxiao_workitem_create_failed")
        self.assertEqual(captured["event_payload"]["step"], "yunxiao_workitem_create")


def _workflow() -> dict:
    return {
        "workflowId": "wf-test-1",
        "requirementKey": "REQ-1",
        "status": "REQUIREMENT_PARSED",
        "dingtalkUrl": "https://alidocs.dingtalk.com/i/nodes/node-123",
        "repoUrl": "https://codeup.example/repo.git",
        "branchName": "feature/REQ-1",
        "yunxiaoTaskId": None,
        "context": {
            "requirement": {
                "summary": "新增客户跟进记录接口",
                "acceptanceCriteria": ["支持新增跟进记录"],
                "affectedRepos": ["jdb-school-crm"],
                "apiChanges": [
                    {
                        "method": "POST",
                        "path": "/crm/client/follow-record",
                        "description": "新增客户跟进记录",
                    }
                ],
                "testScope": ["unit", "api"],
                "risk": "low",
                "openQuestions": [],
                "extra": {"token": "secret-value"},
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
