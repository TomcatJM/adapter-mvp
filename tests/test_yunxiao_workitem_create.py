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
    "YUNXIAO_TASK_WORKITEM_TYPE_IDENTIFIER": "type-task",
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
        self.assertIsNone(result["workitemDisplayId"])
        self.assertEqual(captured["path"], "/organization/org-1/workitem")
        self.assertEqual(captured["action"], "CreateWorkitemV2")
        payload = captured["payload"]
        self.assertEqual(payload["subject"], "新增客户跟进记录接口")
        self.assertEqual(payload["assignedTo"], "account-1")
        self.assertEqual(payload["spaceIdentifier"], "project-1")
        self.assertEqual(payload["category"], "Req")
        self.assertEqual(payload["workitemTypeIdentifier"], "type-req")
        self.assertIn("Workflow：wf-test-1", payload["description"])
        self.assertIn("结构化需求：", payload["description"])
        self.assertIn("- 未提供", payload["description"])
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
        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["method"] == "GET":
                return {"success": True, "id": "YX-PAT-1", "serialNumber": "VEGZ-1186"}
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

        self.assertEqual(pat_request.call_count, 2)
        acs_request.assert_not_called()
        self.assertEqual(result["workitemIdentifier"], "YX-PAT-1")
        self.assertEqual(result["workitemDisplayId"], "VEGZ-1186")
        self.assertEqual(result["authType"], "personal_token")
        self.assertEqual([item["method"] for item in captured], ["POST", "GET"])
        self.assertEqual(captured[0]["path"], "/oapi/v1/projex/organizations/org-pat/workitems")
        self.assertEqual(captured[0]["payload"]["spaceId"], "project-pat")
        self.assertEqual(captured[0]["payload"]["workitemTypeId"], "type-pat")
        self.assertEqual(captured[0]["payload"]["capacityHours"], 1)
        self.assertNotIn("spaceIdentifier", captured[0]["payload"])
        self.assertNotIn("workitemTypeIdentifier", captured[0]["payload"])
        self.assertEqual(captured[0]["config"]["personalToken"], "pat-secret")
        self.assertEqual(captured[1]["path"], "/oapi/v1/projex/organizations/org-pat/workitems/YX-PAT-1")

    def test_personal_token_payload_maps_parent_identifier_to_parent_id(self) -> None:
        from app.yunxiao import _personal_token_workitem_payload

        payload = {
            "subject": "任务一",
            "description": "任务描述",
            "assignedTo": "account-pat",
            "parentIdentifier": "REQ-ROOT",
            "sprint": "sprint-1",
        }

        result = _personal_token_workitem_payload(
            payload,
            {
                "projectId": "project-pat",
                "category": "Task",
                "workitemTypeIdentifier": "type-task",
            },
        )

        self.assertEqual(result["parentId"], "REQ-ROOT")
        self.assertEqual(result["sprint"], "sprint-1")
        self.assertEqual(result["capacityHours"], 1)

    def test_build_payload_resolves_exact_sprint_from_requirement_version_for_personal_token(self) -> None:
        from app.yunxiao import build_create_workitem_payload

        workflow = _workflow()
        workflow["context"]["requirement"]["version"] = "V1.0.0"
        config = {
            "authType": "personal_token",
            "scheme": "https",
            "endpoint": "openapi-rdc.aliyuncs.com",
            "organizationId": "org-pat",
            "projectId": "project-pat",
            "personalToken": "pat-secret",
            "category": "Req",
            "workitemTypeIdentifier": "type-req",
            "assignee": "account-pat",
            "timeout": 30,
        }

        def fake_request(**kwargs):
            self.assertEqual(kwargs["method"], "GET")
            self.assertIn("/sprints?", kwargs["path"])
            return [
                {"id": "sprint-wrong", "name": "CRM-集团-V1.0.0", "status": "TODO"},
                {"id": "sprint-1", "name": "V1.0.0", "status": "TODO"},
            ]

        with patch("app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request):
            payload = build_create_workitem_payload(workflow, config, "codex")

        self.assertEqual(payload["sprint"], "sprint-1")

    def test_build_payload_creates_sprint_when_requirement_version_is_missing_in_yunxiao(self) -> None:
        from app.yunxiao import build_create_workitem_payload

        workflow = _workflow()
        workflow["context"]["requirement"]["version"] = "V1.0.0"
        config = {
            "authType": "personal_token",
            "scheme": "https",
            "endpoint": "openapi-rdc.aliyuncs.com",
            "organizationId": "org-pat",
            "projectId": "project-pat",
            "personalToken": "pat-secret",
            "category": "Req",
            "workitemTypeIdentifier": "type-req",
            "assignee": "account-pat",
            "timeout": 30,
        }
        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["method"] == "GET":
                return [{"id": "sprint-wrong", "name": "CRM-集团-V1.0.0", "status": "TODO"}]
            self.assertEqual(kwargs["method"], "POST")
            self.assertEqual(kwargs["path"], "/oapi/v1/projex/organizations/org-pat/projects/project-pat/sprints")
            self.assertEqual(kwargs["payload"]["name"], "V1.0.0")
            self.assertEqual(kwargs["payload"]["owners"], ["account-pat"])
            self.assertEqual(kwargs["payload"]["capacityHours"], 1)
            return {"id": "sprint-created", "name": "V1.0.0"}

        with patch("app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request):
            payload = build_create_workitem_payload(workflow, config, "codex")

        self.assertEqual(payload["sprint"], "sprint-created")
        self.assertEqual([item["method"] for item in captured], ["GET", "GET", "POST"])

    def test_build_payload_reads_created_sprint_id_from_wrapped_response(self) -> None:
        from app.yunxiao import build_create_workitem_payload

        workflow = _workflow()
        workflow["context"]["requirement"]["version"] = "V1.0.0"
        config = {
            "authType": "personal_token",
            "scheme": "https",
            "endpoint": "openapi-rdc.aliyuncs.com",
            "organizationId": "org-pat",
            "projectId": "project-pat",
            "personalToken": "pat-secret",
            "category": "Req",
            "workitemTypeIdentifier": "type-req",
            "assignee": "account-pat",
            "timeout": 30,
        }

        def fake_request(**kwargs):
            if kwargs["method"] == "GET":
                return []
            return {"success": True, "data": {"id": "sprint-created", "name": "V1.0.0"}}

        with patch("app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request):
            payload = build_create_workitem_payload(workflow, config, "codex")

        self.assertEqual(payload["sprint"], "sprint-created")

    def test_build_payload_does_not_set_sprint_when_requirement_version_is_empty(self) -> None:
        from app.yunxiao import build_create_workitem_payload

        workflow = _workflow()
        workflow["context"]["requirement"]["version"] = ""
        config = {
            "authType": "personal_token",
            "scheme": "https",
            "endpoint": "openapi-rdc.aliyuncs.com",
            "organizationId": "org-pat",
            "projectId": "project-pat",
            "personalToken": "pat-secret",
            "category": "Req",
            "workitemTypeIdentifier": "type-req",
            "assignee": "account-pat",
            "timeout": 30,
        }

        with patch("app.yunxiao._request_yunxiao_personal_token_rest") as request:
            payload = build_create_workitem_payload(workflow, config, "codex")

        self.assertNotIn("sprint", payload)
        request.assert_not_called()

    def test_create_workitem_tree_creates_parent_and_child_tasks(self) -> None:
        from app.yunxiao import create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"] = {
            "summary": "新增客户跟进记录接口",
            "demands": [
                {
                    "demandIndex": 1,
                    "title": "需求一",
                    "description": "描述：1111111",
                    "items": [
                        {
                            "itemIndex": 1,
                            "title": "任务一",
                            "parentDemandIndex": 1,
                            "parentDemandTitle": "旧解析值",
                            "ownerName": "姬志猛",
                            "contentLines": ["创建一条学生信息", "姓名必填", "手机号必填"],
                        }
                    ],
                }
            ],
        }
        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            subject = kwargs["payload"]["subject"]
            if subject == "需求一":
                return {"success": True, "workitemIdentifier": "REQ-ROOT", "requestId": "req-1"}
            if subject == "任务一":
                self.assertEqual(kwargs["payload"]["parentIdentifier"], "REQ-ROOT")
                return {"success": True, "workitemIdentifier": "TASK-1", "requestId": "req-2"}
            raise AssertionError(f"unexpected subject: {subject}")

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao.db.find_yunxiao_project_member",
            side_effect=lambda project_name, member_name: {
                "projectName": project_name,
                "name": member_name,
                "accountId": "user-jzm",
                "isDefault": False,
            }
            if member_name == "姬志猛"
            else None,
        ), patch("app.yunxiao.db.find_default_yunxiao_project_member", return_value=None), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = create_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["workitemIdentifier"], "REQ-ROOT")
        self.assertEqual(result["demandCount"], 1)
        self.assertEqual(result["taskCount"], 1)
        self.assertEqual(result["taskIdentifiers"], ["TASK-1"])
        self.assertEqual(result["demands"][0]["workitemIdentifier"], "REQ-ROOT")
        self.assertEqual(result["demands"][0]["items"][0]["workitemIdentifier"], "TASK-1")
        self.assertEqual(result["demands"][0]["items"][0]["parentDemandTitle"], "需求一")
        self.assertEqual([item["payload"]["subject"] for item in captured], ["需求一", "任务一"])
        self.assertEqual(captured[0]["payload"]["category"], "Req")
        self.assertEqual(captured[0]["payload"]["workitemTypeIdentifier"], "type-req")
        self.assertEqual(captured[1]["payload"]["category"], "Task")
        self.assertEqual(captured[1]["payload"]["workitemTypeIdentifier"], "type-task")
        self.assertEqual(captured[1]["payload"]["parentIdentifier"], "REQ-ROOT")
        self.assertEqual(result["demands"][0]["category"], "Req")
        self.assertEqual(result["demands"][0]["workitemTypeIdentifier"], "type-req")
        self.assertEqual(result["demands"][0]["items"][0]["category"], "Task")
        self.assertEqual(result["demands"][0]["items"][0]["workitemTypeIdentifier"], "type-task")
        self.assertIn("主要内容：", captured[1]["payload"]["description"])

    def test_create_workitem_tree_requires_task_workitem_type_for_items(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"] = {
            "summary": "新增客户跟进记录接口",
            "demands": [
                {
                    "demandIndex": 1,
                    "title": "需求一",
                    "items": [{"itemIndex": 1, "title": "任务一"}],
                }
            ],
        }
        env_without_task_type = {key: value for key, value in ENV.items() if key != "YUNXIAO_TASK_WORKITEM_TYPE_IDENTIFIER"}

        with patch.dict(os.environ, env_without_task_type, clear=True):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        self.assertIn("Yunxiao task workitem type is missing", str(raised.exception))

    def test_task_description_uses_current_demand_as_summary(self) -> None:
        from app.yunxiao import _build_requirement_task_description

        workflow = _workflow()
        requirement = {
            "summary": "需求一",
        }
        demand = {
            "title": "需求二",
            "description": "222222222222",
        }
        item = {
            "title": "创建跟进记录二",
            "ownerName": "",
            "contentLines": ["新建跟进记录22222", "类型、内容必填2222"],
        }

        description = _build_requirement_task_description(workflow, requirement, demand, item, "codex")

        self.assertIn("所属需求：需求二", description)
        self.assertIn("需求摘要：\n需求二", description)
        self.assertNotIn("需求摘要：\n需求一", description)

    def test_demand_description_uses_current_demand_as_summary(self) -> None:
        from app.yunxiao import _build_requirement_demand_description

        workflow = _workflow()
        requirement = {
            "summary": "需求一",
        }
        demand = {
            "title": "需求二",
            "description": "222222222222",
            "items": [{"title": "任务二"}],
        }

        description = _build_requirement_demand_description(workflow, requirement, demand, "codex")

        self.assertIn("需求标题：需求二", description)
        self.assertIn("需求摘要：\n需求二", description)
        self.assertNotIn("需求摘要：\n需求一", description)

    def test_create_workitem_tree_requires_explicit_demand_title(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["requirementKey"] = "REQ-FALLBACK"
        workflow["context"]["requirement"] = {
            "summary": "需求一",
            "documentTitle": "文档标题不能当需求标题",
            "demands": [
                {
                    "demandIndex": 1,
                    "description": "描述：1111111",
                    "items": [],
                }
            ],
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao._request_yunxiao_openapi") as request_mock:
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        self.assertIn("Requirement demand title is required", str(raised.exception))
        self.assertIn("Do not infer it from documentTitle", str(raised.exception))
        request_mock.assert_not_called()

    def test_create_workitem_tree_missing_requested_owner_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"] = {
            "summary": "新增客户跟进记录接口",
            "demands": [
                {
                    "demandIndex": 1,
                    "title": "需求一",
                    "description": "描述：1111111",
                    "items": [
                        {
                            "itemIndex": 1,
                            "title": "任务一",
                            "parentDemandIndex": 1,
                            "parentDemandTitle": "需求一",
                            "ownerName": "不存在的人",
                            "contentLines": ["创建一条学生信息"],
                        }
                    ],
                }
            ],
        }
        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            subject = kwargs["payload"]["subject"]
            if subject == "需求一":
                return {"success": True, "workitemIdentifier": "REQ-ROOT", "requestId": "req-1"}
            raise AssertionError(f"unexpected subject: {subject}")

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.db.find_yunxiao_project_member", return_value=None), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member",
            return_value={
                "projectName": "jdb-school-crm",
                "name": "默认负责人",
                "accountId": "user-default",
                "isDefault": True,
            },
        ), patch("app.yunxiao._request_yunxiao_openapi", side_effect=fake_request):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        self.assertIn("Yunxiao assignee config missing", str(raised.exception))
        self.assertIn("assignee=不存在的人", str(raised.exception))
        self.assertEqual(captured, [])

    def test_create_workitem_tree_failure_exposes_partial_result(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"] = {
            "summary": "新增客户跟进记录接口",
            "demands": [
                {
                    "demandIndex": 1,
                    "title": "需求一",
                    "description": "描述：1111111",
                    "items": [
                        {
                            "itemIndex": 1,
                            "title": "任务一",
                            "parentDemandIndex": 1,
                            "parentDemandTitle": "需求一",
                            "ownerName": "不存在的人",
                            "contentLines": ["创建一条学生信息"],
                        }
                    ],
                }
            ],
        }

        def fake_request(**kwargs):
            subject = kwargs["payload"]["subject"]
            if subject == "需求一":
                return {"success": True, "workitemIdentifier": "REQ-ROOT", "requestId": "req-1"}
            raise AssertionError(f"unexpected subject: {subject}")

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.db.find_yunxiao_project_member", return_value=None), patch(
            "app.yunxiao.db.find_default_yunxiao_project_member",
            return_value={
                "projectName": "jdb-school-crm",
                "name": "默认负责人",
                "accountId": "user-default",
                "isDefault": True,
            },
        ), patch("app.yunxiao._request_yunxiao_openapi", side_effect=fake_request):
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        self.assertIn("Yunxiao requirement tree creation failed", str(raised.exception))
        partial_result = getattr(raised.exception, "partial_result", None)
        self.assertIsNotNone(partial_result)
        self.assertEqual(partial_result["demandCount"], 0)
        self.assertEqual(partial_result["taskCount"], 0)
        self.assertEqual(partial_result["taskIdentifiers"], [])

    def test_create_workitem_tree_missing_requested_owner_lists_project_members(self) -> None:
        from app.yunxiao import YunxiaoError, create_yunxiao_workitem

        workflow = _workflow()
        workflow["context"]["requirement"] = {
            "summary": "新增客户跟进记录接口",
            "demands": [
                {
                    "demandIndex": 1,
                    "title": "需求一",
                    "items": [
                        {
                            "itemIndex": 1,
                            "title": "任务一",
                            "ownerName": "未配置负责人",
                            "contentLines": ["创建一条学生信息"],
                        }
                    ],
                }
            ],
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.db.find_yunxiao_project_member", return_value=None), patch(
            "app.yunxiao.db.list_yunxiao_project_members",
            return_value=[
                {"name": "姬志猛", "accountId": "user-jzm"},
                {"name": "谢铭琪", "accountId": "user-xmq"},
            ],
        ), patch("app.yunxiao._request_yunxiao_openapi") as request_mock:
            with self.assertRaises(YunxiaoError) as raised:
                create_yunxiao_workitem(workflow, "codex")

        message = str(raised.exception)
        self.assertIn("Yunxiao assignee config missing", message)
        self.assertIn("assignee=未配置负责人", message)
        self.assertIn("Available project members: 姬志猛, 谢铭琪", message)
        request_mock.assert_not_called()

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
        self.assertIn("adapter_yunxiao_member", str(raised.exception))
        self.assertIn("adapter_yunxiao_project_member_relation", str(raised.exception))

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
                "workitemDisplayId": "VEGZ-1186",
                "requestId": "req-1",
                "projectId": "project-1",
                "category": "Req",
                "workitemTypeIdentifier": "type-req",
                "title": "新增客户跟进记录接口",
                "sprintId": "sprint-1",
            },
        ), patch("app.workflow.db.update_workflow_yunxiao_task_created", side_effect=fake_created), patch(
            "app.workflow.db.update_workflow_coding_requested", side_effect=fake_coding
        ):
            result = advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertTrue(result["advanced"])
        self.assertEqual(result["workflow"]["status"], "CODING_REQUESTED")
        self.assertEqual(result["workflow"]["yunxiaoTaskId"], "YX-1")
        self.assertEqual(result["yunxiao"]["workitemDisplayId"], "VEGZ-1186")
        self.assertEqual(captured["created"]["from_status"], "REQUIREMENT_PARSED")
        self.assertEqual(captured["created"]["yunxiao_task_id"], "YX-1")
        self.assertEqual(captured["created"]["context"]["yunxiao"]["createResult"]["sprintId"], "sprint-1")
        self.assertEqual(captured["created"]["event_payload"]["yunxiaoTaskDisplayId"], "VEGZ-1186")
        self.assertEqual(captured["coding"]["event_payload"]["yunxiaoTaskId"], "YX-1")
        self.assertEqual(captured["coding"]["event_payload"]["yunxiaoTaskDisplayId"], "VEGZ-1186")

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

    def test_advance_requirement_parsed_records_partial_tree_checkpoint_on_create_failure(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import WorkflowError, advance_workflow
        from app.yunxiao import YunxiaoError

        workflow = _workflow()
        captured = {}
        exc = YunxiaoError("Yunxiao requirement tree creation failed")
        exc.partial_result = {
            "demandCount": 1,
            "taskCount": 1,
            "taskIdentifiers": ["TASK-1"],
        }

        def fake_record(**kwargs):
            captured.update(kwargs)
            return {**workflow, "lastError": kwargs["error"], "retryCount": 1}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.create_yunxiao_workitem", side_effect=exc
        ), patch("app.workflow.db.record_workflow_error", side_effect=fake_record):
            with self.assertRaises(WorkflowError):
                advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertEqual(captured["status"], "REQUIREMENT_PARSED")
        self.assertEqual(captured["event_type"], "yunxiao_workitem_create_failed")
        self.assertEqual(captured["event_payload"]["step"], "yunxiao_workitem_create")
        self.assertEqual(captured["event_payload"]["partialResult"]["taskIdentifiers"], ["TASK-1"])

    def test_delete_workitems_dry_run_does_not_call_yunxiao(self) -> None:
        from app.yunxiao import delete_yunxiao_workitems

        workflow = _workflow()
        with _patch_personal_token_config(), patch(
            "app.yunxiao._request_yunxiao_personal_token_rest"
        ) as request_mock:
            result = delete_yunxiao_workitems(workflow, ["TASK-1", "REQ-1"], operator="codex", dry_run=True)

        self.assertTrue(result["dryRun"])
        self.assertEqual(result["deletePlan"], ["TASK-1", "REQ-1"])
        self.assertEqual(result["deleted"], [])
        request_mock.assert_not_called()

    def test_delete_workitems_explicit_ids_do_not_expand_to_workflow_tasks(self) -> None:
        from app.yunxiao import delete_yunxiao_workitems

        workflow = _workflow_with_requirement_tree()
        with _patch_personal_token_config():
            result = delete_yunxiao_workitems(workflow, ["TASK-1"], operator="codex", dry_run=True, include_demands=True)

        self.assertEqual(result["deletePlan"], ["TASK-1"])

    def test_delete_workitems_requires_personal_token_auth(self) -> None:
        from app.yunxiao import YunxiaoError, delete_yunxiao_workitems

        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(YunxiaoError) as raised:
                delete_yunxiao_workitems(_workflow(), ["TASK-1"], operator="codex", dry_run=False)

        self.assertIn("requires personal_token auth", str(raised.exception))

    def test_delete_workitems_calls_personal_token_delete(self) -> None:
        from app.yunxiao import delete_yunxiao_workitems

        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            return {"success": True}

        with _patch_personal_token_config(), patch(
            "app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request
        ):
            result = delete_yunxiao_workitems(_workflow(), ["TASK-1", "REQ-1"], operator="codex", dry_run=False)

        self.assertFalse(result["dryRun"])
        self.assertEqual([item["workitemIdentifier"] for item in result["deleted"]], ["TASK-1", "REQ-1"])
        self.assertEqual([call["method"] for call in captured], ["DELETE", "DELETE"])
        self.assertEqual(captured[0]["path"], "/oapi/v1/projex/organizations/org-1/workitems/TASK-1")


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


def _workflow_with_requirement_tree() -> dict:
    workflow = _workflow()
    workflow["context"]["yunxiao"] = {
        "createResult": {
            "workitemIdentifier": "REQ-ROOT",
            "workitemDisplayId": "REQ-ROOT-DISPLAY",
            "demandCount": 1,
            "taskCount": 2,
            "taskIdentifiers": ["TASK-1", "TASK-2"],
            "demands": [
                {
                    "workitemIdentifier": "REQ-ROOT",
                    "workitemDisplayId": "REQ-ROOT-DISPLAY",
                    "items": [
                        {
                            "workitemIdentifier": "TASK-1",
                            "workitemDisplayId": "TASK-1-DISPLAY",
                            "category": "Task",
                            "parentIdentifier": "REQ-ROOT",
                        },
                        {
                            "workitemIdentifier": "TASK-2",
                            "workitemDisplayId": "TASK-2-DISPLAY",
                            "category": "Task",
                            "parentIdentifier": "REQ-ROOT",
                        },
                    ],
                }
            ],
        }
    }
    return workflow


def _patch_personal_token_config():
    project_config = {
        "projectName": "jdb-school-crm",
        "accountName": "pat-main",
        "organizationId": "org-1",
        "projectId": "project-1",
        "category": "Req",
        "workitemTypeIdentifier": "type-1",
        "assignee": "user-1",
    }
    account_config = {
        "accountName": "pat-main",
        "authType": "personal_token",
        "legacyToken": "pat-secret",
        "endpoint": "devops.cn-hangzhou.aliyuncs.com",
    }
    return patch.multiple(
        "app.yunxiao.db",
        configured=lambda: True,
        find_yunxiao_project_config=lambda project_name: project_config,
        find_yunxiao_account_config=lambda account_name: account_config,
    )


if __name__ == "__main__":
    unittest.main()
