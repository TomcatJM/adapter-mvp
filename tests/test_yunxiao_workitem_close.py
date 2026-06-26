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
    "YUNXIAO_DONE_STATUS_ID": "done",
}


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class YunxiaoWorkitemCloseTest(unittest.TestCase):
    def test_close_workitem_writes_comment_and_updates_done_status(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured: list[dict] = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            action = kwargs["action"]
            if action == "GetWorkItemInfo" and len([item for item in captured if item["action"] == action]) == 1:
                return {"success": True, "data": {"identifier": "YX-1", "statusIdentifier": "doing"}}
            if action == "GetWorkItemInfo":
                return {"success": True, "data": {"identifier": "YX-1", "statusIdentifier": "done"}}
            return {"success": True, "requestId": f"req-{len(captured)}"}

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(_workflow(), "codex")

        self.assertFalse(result["alreadyClosed"])
        self.assertEqual(result["writeback"], "success")
        self.assertEqual(result["closedStatus"], "done")
        self.assertEqual([item["action"] for item in captured], [
            "GetWorkItemInfo",
            "CreateWorkitemComment",
            "UpdateWorkItem",
            "GetWorkItemInfo",
        ])
        comment_payload = captured[1]["payload"]
        self.assertIn("【Adapter 交付回写】", comment_payload["content"])
        self.assertIn("Workflow：wf-close-1", comment_payload["content"])
        self.assertIn("Apifox：已同步", comment_payload["content"])
        self.assertNotIn("secret-value", comment_payload["content"])
        update_payload = captured[2]["payload"]
        self.assertEqual(update_payload["identifier"], "YX-1")
        self.assertEqual(update_payload["propertyKey"], "status")
        self.assertEqual(update_payload["propertyValue"], "done")
        self.assertEqual(update_payload["fieldType"], "status")

    def test_close_workitem_already_closed_is_idempotent(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            return {"success": True, "data": {"identifier": "YX-1", "statusIdentifier": "done"}}

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(_workflow(), "codex")

        self.assertTrue(result["alreadyClosed"])
        self.assertEqual(result["writeback"], "skipped")
        self.assertEqual([item["action"] for item in captured], ["GetWorkItemInfo"])

    def test_close_workitem_tree_only_closes_child_tasks_and_mentions_each_task(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured: list[dict] = []
        task_lookup_counts = {"TASK-1": 0, "TASK-2": 0}

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["action"] == "GetWorkItemInfo":
                path = kwargs["path"]
                if path.endswith("/REQ-ROOT"):
                    return {"success": True, "data": {"identifier": "REQ-ROOT", "serialNumber": "REQ-ROOT-DISPLAY", "statusIdentifier": "new"}}
                if path.endswith("/TASK-1"):
                    task_lookup_counts["TASK-1"] += 1
                    status = "doing" if task_lookup_counts["TASK-1"] == 1 else "done"
                    return {"success": True, "data": {"identifier": "TASK-1", "serialNumber": "TASKA-1186", "statusIdentifier": status}}
                if path.endswith("/TASK-2"):
                    task_lookup_counts["TASK-2"] += 1
                    status = "doing" if task_lookup_counts["TASK-2"] == 1 else "done"
                    return {"success": True, "data": {"identifier": "TASK-2", "serialNumber": "TASKB-1187", "statusIdentifier": status}}
                raise AssertionError(f"unexpected task lookup path: {path}")
            return {"success": True, "requestId": f"req-{len(captured)}"}

        workflow = {
            "workflowId": "wf-close-tree-1",
            "requirementKey": "REQ-1",
            "status": "APIFOX_SYNCED",
            "dingtalkUrl": "https://alidocs.dingtalk.com/i/nodes/node-123",
            "repoUrl": "https://codeup.example/repo.git",
            "branchName": "feature/REQ-1",
            "commitId": "abc123",
            "yunxiaoTaskId": "REQ-ROOT",
            "yunxiaoPipelineId": "pipe-1",
            "yunxiaoBuildNumber": "42",
            "apifoxProjectId": "8460173",
            "context": {
                "projectName": "jdb-school-crm",
                "requirement": {
                    "summary": "新增客户跟进记录接口",
                    "affectedRepos": ["jdb-school-crm"],
                },
                "yunxiao": {
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
                                "category": "Req",
                                "items": [
                                    {
                                        "workitemIdentifier": "TASK-1",
                                        "workitemDisplayId": "TASKA-1186",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-ROOT",
                                    },
                                    {
                                        "workitemIdentifier": "TASK-2",
                                        "workitemDisplayId": "TASKB-1187",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-ROOT",
                                    },
                                ],
                            }
                        ],
                    }
                },
                "codingResult": {
                    "branchName": "feature/REQ-1",
                    "commitId": "abc123",
                    "mergeRequestUrl": "https://codeup.example/mr/1",
                },
                "pipeline": {
                    "pipelineId": "pipe-1",
                    "buildNumber": "42",
                    "branchName": "feature/REQ-1",
                    "commitId": "abc123",
                    "commitMessage": "feat: close selected tasks\n\n云效任务: TASKA-1186、 TASKB-1187",
                },
                "apifox": {
                    "lastResult": {
                        "imported": True,
                        "projectId": "8460173",
                    }
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["closedTaskIds"], ["TASK-1", "TASK-2"])
        self.assertEqual(result["skippedTaskIds"], [])
        get_paths = [item["path"] for item in captured if item["action"] == "GetWorkItemInfo"]
        self.assertEqual(get_paths, [
            "/organization/org-1/workitems/REQ-ROOT",
            "/organization/org-1/workitems/TASK-1",
            "/organization/org-1/workitems/TASK-1",
            "/organization/org-1/workitems/TASK-2",
            "/organization/org-1/workitems/TASK-2",
            "/organization/org-1/workitems/REQ-ROOT",
        ])
        comment_payloads = [item["payload"]["content"] for item in captured if item["action"] == "CreateWorkitemComment"]
        self.assertEqual(len(comment_payloads), 2)
        self.assertIn("云效工作项：TASKA-1186", comment_payloads[0])
        self.assertIn("云效工作项：TASKB-1187", comment_payloads[1])
        self.assertNotIn("REQ-ROOT-DISPLAY", comment_payloads[0])
        self.assertNotIn("REQ-ROOT-DISPLAY", comment_payloads[1])

    def test_close_workitem_tree_only_closes_commit_listed_child_task_display_ids(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured: list[dict] = []
        task_lookup_counts = {"TASK-1": 0, "TASK-2": 0}

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["action"] == "GetWorkItemInfo":
                path = kwargs["path"]
                if path.endswith("/REQ-ROOT"):
                    return {"success": True, "data": {"identifier": "REQ-ROOT", "serialNumber": "REQ-ROOT-DISPLAY", "statusIdentifier": "new"}}
                if path.endswith("/TASK-1"):
                    task_lookup_counts["TASK-1"] += 1
                    return {"success": True, "data": {"identifier": "TASK-1", "serialNumber": "TASKA-1186", "statusIdentifier": "doing"}}
                if path.endswith("/TASK-2"):
                    task_lookup_counts["TASK-2"] += 1
                    status = "doing" if task_lookup_counts["TASK-2"] == 1 else "done"
                    return {"success": True, "data": {"identifier": "TASK-2", "serialNumber": "TASKB-1187", "statusIdentifier": status}}
                raise AssertionError(f"unexpected task lookup path: {path}")
            return {"success": True, "requestId": f"req-{len(captured)}"}

        workflow = {
            **_workflow(),
            "workflowId": "wf-close-tree-selected",
            "yunxiaoTaskId": "REQ-ROOT",
            "context": {
                **_workflow()["context"],
                "yunxiao": {
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
                                "category": "Req",
                                "items": [
                                    {
                                        "workitemIdentifier": "TASK-1",
                                        "workitemDisplayId": "TASKA-1186",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-ROOT",
                                    },
                                    {
                                        "workitemIdentifier": "TASK-2",
                                        "workitemDisplayId": "TASKB-1187",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-ROOT",
                                    },
                                ],
                            }
                        ],
                    }
                },
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: close selected task\n\n云效任务: TASKB-1187",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["closedTaskIds"], ["TASK-2"])
        self.assertEqual(result["skippedTaskIds"], [])
        get_paths = [item["path"] for item in captured if item["action"] == "GetWorkItemInfo"]
        self.assertEqual(get_paths, [
            "/organization/org-1/workitems/REQ-ROOT",
            "/organization/org-1/workitems/TASK-2",
            "/organization/org-1/workitems/TASK-2",
            "/organization/org-1/workitems/REQ-ROOT",
        ])
        comment_payloads = [item["payload"]["content"] for item in captured if item["action"] == "CreateWorkitemComment"]
        self.assertEqual(len(comment_payloads), 1)
        self.assertIn("云效工作项：TASKB-1187", comment_payloads[0])
        self.assertNotIn("TASKA-1186", comment_payloads[0])

    def test_close_workitem_tree_restores_parent_demands_after_yunxiao_cascade(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured: list[dict] = []
        lookup_counts: dict[str, int] = {}

        def fake_request(**kwargs):
            captured.append(kwargs)
            action = kwargs["action"]
            if action == "GetWorkItemInfo":
                workitem_id = kwargs["path"].rsplit("/", 1)[-1]
                lookup_counts[workitem_id] = lookup_counts.get(workitem_id, 0) + 1
                count = lookup_counts[workitem_id]
                if workitem_id in {"REQ-1", "REQ-2"}:
                    status = "new" if count in {1, 3} else "done"
                    return {"success": True, "data": {"identifier": workitem_id, "serialNumber": f"{workitem_id}-DISPLAY", "statusIdentifier": status}}
                if workitem_id in {"TASK-1", "TASK-2"}:
                    status = "doing" if count == 1 else "done"
                    return {"success": True, "data": {"identifier": workitem_id, "serialNumber": f"{workitem_id}-DISPLAY", "statusIdentifier": status}}
                raise AssertionError(f"unexpected lookup path: {kwargs['path']}")
            return {"success": True, "requestId": f"req-{len(captured)}"}

        workflow = {
            **_workflow(),
            "workflowId": "wf-close-tree-cascade",
            "yunxiaoTaskId": "REQ-1",
            "context": {
                **_workflow()["context"],
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "REQ-1",
                        "workitemDisplayId": "REQ-1-DISPLAY",
                        "demandCount": 2,
                        "taskCount": 2,
                        "taskIdentifiers": ["TASK-1", "TASK-2"],
                        "demands": [
                            {
                                "workitemIdentifier": "REQ-1",
                                "workitemDisplayId": "REQ-1-DISPLAY",
                                "category": "Req",
                                "items": [
                                    {
                                        "workitemIdentifier": "TASK-1",
                                        "workitemDisplayId": "TASK-1-DISPLAY",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-1",
                                    }
                                ],
                            },
                            {
                                "workitemIdentifier": "REQ-2",
                                "workitemDisplayId": "REQ-2-DISPLAY",
                                "category": "Req",
                                "items": [
                                    {
                                        "workitemIdentifier": "TASK-2",
                                        "workitemDisplayId": "TASK-2-DISPLAY",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-2",
                                    }
                                ],
                            },
                        ],
                    }
                },
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: close selected tasks\n\n云效任务: TASK-1-DISPLAY、 TASK-2-DISPLAY",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(workflow, "codex")

        self.assertEqual(result["closedTaskIds"], ["TASK-1", "TASK-2"])
        self.assertEqual(result["restoredDemandIds"], ["REQ-1", "REQ-2"])
        update_payloads = [item["payload"] for item in captured if item["action"] == "UpdateWorkItem"]
        self.assertEqual(
            [(payload["identifier"], payload["propertyValue"]) for payload in update_payloads],
            [("TASK-1", "done"), ("TASK-2", "done"), ("REQ-1", "new"), ("REQ-2", "new")],
        )
        comment_payloads = [item["payload"]["content"] for item in captured if item["action"] == "CreateWorkitemComment"]
        self.assertEqual(len(comment_payloads), 2)
        self.assertNotIn("REQ-1-DISPLAY", comment_payloads[0])
        self.assertNotIn("REQ-2-DISPLAY", comment_payloads[1])

    def test_close_workitem_missing_task_id_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "yunxiaoTaskId": None,
            "context": {
                **_workflow()["context"],
                "yunxiao": {},
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: close selected task\n\n云效任务: YX-1",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True):
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(workflow, "codex")

        self.assertIn("Yunxiao task id missing", str(raised.exception))
        self.assertIn("create or bind", str(raised.exception))

    def test_close_workitem_without_commit_yunxiao_task_ids_skips_without_api_call(self) -> None:
        from app.yunxiao import YunxiaoCloseSkipped, close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "context": {
                **_workflow()["context"],
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: no explicit close ids",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.get_yunxiao_workitem") as get_workitem:
            with self.assertRaises(YunxiaoCloseSkipped) as raised:
                close_yunxiao_workitem(workflow, "codex")

        get_workitem.assert_not_called()
        self.assertIn("explicit close task ids missing", str(raised.exception))

    def test_close_workitem_tree_without_child_task_ids_fails_before_root_close(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "yunxiaoTaskId": "REQ-ROOT",
            "context": {
                **_workflow()["context"],
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "REQ-ROOT",
                        "category": "Req",
                        "demandCount": 1,
                        "taskCount": 1,
                        "demands": [
                            {
                                "workitemIdentifier": "REQ-ROOT",
                                "category": "Req",
                                "items": [],
                            }
                        ],
                        "taskIdentifiers": [],
                    }
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.get_yunxiao_workitem") as get_workitem:
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(workflow, "codex")

        get_workitem.assert_not_called()
        self.assertIn("requirement-tree workflow must have child task ids", str(raised.exception))

    def test_close_workitem_tree_rejects_root_requirement_in_task_ids(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "yunxiaoTaskId": "REQ-ROOT",
            "context": {
                **_workflow()["context"],
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "REQ-ROOT",
                        "category": "Req",
                        "demandCount": 1,
                        "taskCount": 1,
                        "demands": [
                            {
                                "workitemIdentifier": "REQ-ROOT",
                                "category": "Req",
                                "items": [
                                    {
                                        "workitemIdentifier": "REQ-ROOT",
                                        "category": "Task",
                                        "parentIdentifier": "REQ-ROOT",
                                    }
                                ],
                            }
                        ],
                        "taskIdentifiers": ["REQ-ROOT"],
                    }
                },
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: invalid root close\n\n云效任务: REQ-ROOT",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.get_yunxiao_workitem") as get_workitem:
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(workflow, "codex")

        get_workitem.assert_not_called()
        self.assertIn("must not include root requirement id", str(raised.exception))

    def test_close_workitem_tree_rejects_demand_id_even_when_listed_as_task_identifier(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "yunxiaoTaskId": "REQ-ROOT",
            "context": {
                **_workflow()["context"],
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "REQ-ROOT",
                        "category": "Req",
                        "demandCount": 1,
                        "taskCount": 1,
                        "demands": [
                            {
                                "workitemIdentifier": "REQ-1",
                                "category": "Req",
                                "items": [],
                            }
                        ],
                        "taskIdentifiers": ["REQ-1"],
                    }
                },
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": "feat: invalid demand close\n\n云效任务: REQ-1",
                },
            },
        }

        with patch.dict(os.environ, ENV, clear=True), patch("app.yunxiao.get_yunxiao_workitem") as get_workitem:
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(workflow, "codex")

        get_workitem.assert_not_called()
        self.assertIn("must not include requirement demand id", str(raised.exception))

    def test_close_workitem_accepts_explicit_refs_argument_when_commit_message_missing(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        workflow = {
            **_workflow(),
            "context": {
                **_workflow()["context"],
                "pipeline": {
                    **_workflow()["context"]["pipeline"],
                    "commitMessage": None,
                },
            },
        }
        captured: list[dict] = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["action"] == "GetWorkItemInfo" and len([item for item in captured if item["action"] == "GetWorkItemInfo"]) == 1:
                return {"success": True, "data": {"identifier": "YX-1", "serialNumber": "VEGZ-1186", "statusIdentifier": "doing"}}
            if kwargs["action"] == "GetWorkItemInfo":
                return {"success": True, "data": {"identifier": "YX-1", "serialNumber": "VEGZ-1186", "statusIdentifier": "done"}}
            return {"success": True}

        with patch.dict(os.environ, ENV, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi", side_effect=fake_request
        ):
            result = close_yunxiao_workitem(workflow, "codex", explicit_refs=["VEGZ-1186"])

        self.assertEqual(result["closedTaskIds"], ["YX-1"])
        self.assertEqual([item["action"] for item in captured], [
            "GetWorkItemInfo",
            "CreateWorkitemComment",
            "UpdateWorkItem",
            "GetWorkItemInfo",
        ])

    def test_close_workitem_missing_done_status_fails_explicitly(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        env = {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "ak-test",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret-test",
            "YUNXIAO_ORGANIZATION_ID": "org-1",
            "YUNXIAO_PROJECT_ID": "project-1",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "app.yunxiao._request_yunxiao_openapi",
            return_value={"success": True, "data": {"identifier": "YX-1", "statusIdentifier": "doing"}},
        ):
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(_workflow(), "codex")

        self.assertIn("Yunxiao close config missing", str(raised.exception))
        self.assertIn("done_status_id", str(raised.exception))

    def test_close_workitem_legacy_token_fails_with_ak_solution(self) -> None:
        from app.yunxiao import YunxiaoError, close_yunxiao_workitem

        project_config = {
            "projectName": "jdb-school-crm",
            "accountName": "legacy-openclaw",
            "organizationId": "org-1",
            "projectId": "project-1",
            "category": "Req",
            "workitemTypeIdentifier": "type-1",
            "assignee": "user-1",
            "doneStatusId": "done",
            "doneStatusFieldId": "status",
            "doneStatusNames": "已完成,done",
        }
        account_config = {
            "accountName": "legacy-openclaw",
            "authType": "legacy_token",
            "legacyToken": "token-test",
            "endpoint": "https://openapi-rdc.aliyuncs.com",
        }

        with patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config", return_value=project_config
        ), patch("app.yunxiao.db.find_yunxiao_account_config", return_value=account_config), patch(
            "app.yunxiao.get_yunxiao_workitem"
        ) as get_workitem:
            with self.assertRaises(YunxiaoError) as raised:
                close_yunxiao_workitem(_workflow(), "codex")

        get_workitem.assert_not_called()
        self.assertIn("requires acs_ak OpenAPI auth", str(raised.exception))
        self.assertIn("legacy_token", str(raised.exception))
        self.assertIn("access_key_id", str(raised.exception))

    def test_close_workitem_uses_personal_token_api(self) -> None:
        from app.yunxiao import close_yunxiao_workitem

        captured: list[dict] = []

        def fake_request(**kwargs):
            captured.append(kwargs)
            if kwargs["method"] == "GET" and len([item for item in captured if item["method"] == "GET"]) == 1:
                return {"success": True, "identifier": "YX-1", "status": "doing"}
            if kwargs["method"] == "GET":
                return {"success": True, "identifier": "YX-1", "status": "done"}
            return {"success": True}

        project_config = {
            "projectName": "jdb-school-crm",
            "accountName": "pat-main",
            "organizationId": "org-1",
            "projectId": "project-1",
            "category": "Req",
            "workitemTypeIdentifier": "type-1",
            "assignee": "user-1",
            "doneStatusId": "done",
            "doneStatusFieldId": "status",
            "doneStatusNames": "已完成,done",
            "commentFormatType": "MARKDOWN",
        }
        account_config = {
            "accountName": "pat-main",
            "authType": "personal_token",
            "legacyToken": "pat-secret",
            "endpoint": "devops.cn-hangzhou.aliyuncs.com",
        }

        with patch("app.yunxiao.db.configured", return_value=True), patch(
            "app.yunxiao.db.find_yunxiao_project_config", return_value=project_config
        ), patch("app.yunxiao.db.find_yunxiao_account_config", return_value=account_config), patch(
            "app.yunxiao._request_yunxiao_personal_token_rest", side_effect=fake_request
        ) as pat_request, patch(
            "app.yunxiao._request_yunxiao_openapi"
        ) as acs_request:
            result = close_yunxiao_workitem(_workflow(), "codex")

        self.assertEqual(result["authType"], "personal_token")
        self.assertEqual(result["writeback"], "success")
        self.assertEqual(result["closedStatus"], "done")
        self.assertEqual([item["method"] for item in captured], ["GET", "POST", "PUT", "GET"])
        self.assertEqual(captured[0]["path"], "/oapi/v1/projex/organizations/org-1/workitems/YX-1")
        self.assertEqual(captured[1]["path"], "/oapi/v1/projex/organizations/org-1/workitems/YX-1/comments")
        self.assertIn("【Adapter 交付回写】", captured[1]["payload"]["content"])
        self.assertEqual(captured[2]["payload"], {"status": "done"})
        pat_request.assert_called()
        acs_request.assert_not_called()

    def test_advance_apifox_synced_closes_workitem(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = _workflow()
        captured = {}

        def fake_closed(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": "YUNXIAO_TASK_CLOSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem",
            return_value={
                "workitemIdentifier": "YX-1",
                "workitemDisplayId": "VEGZ-1186",
                "alreadyClosed": False,
                "closedStatus": "done",
                "closedStatusName": "已完成",
                "writeback": "success",
                "configSource": "env",
            },
        ), patch("app.workflow.db.update_workflow_yunxiao_task_closed", side_effect=fake_closed):
            result = advance_workflow("wf-close-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertTrue(result["advanced"])
        self.assertEqual(result["workflow"]["status"], "YUNXIAO_TASK_CLOSED")
        self.assertEqual(captured["event_type"], "yunxiao_workitem_closed")
        self.assertEqual(captured["event_payload"]["yunxiaoTaskId"], "YX-1")
        self.assertEqual(captured["event_payload"]["yunxiaoTaskDisplayId"], "VEGZ-1186")
        self.assertEqual(captured["event_payload"]["writeback"], "success")
        self.assertEqual(captured["context"]["yunxiao"]["closeResult"]["workitemDisplayId"], "VEGZ-1186")
        self.assertEqual(captured["context"]["yunxiao"]["closeResult"]["closedStatus"], "done")

    def test_advance_apifox_synced_compensates_already_closed_workitem(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = _workflow()
        captured = {}

        def fake_closed(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": "YUNXIAO_TASK_CLOSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem",
            return_value={
                "workitemIdentifier": "YX-1",
                "alreadyClosed": True,
                "closedStatus": "done",
                "closedStatusName": "已完成",
                "writeback": "skipped",
                "configSource": "env",
            },
        ), patch("app.workflow.db.update_workflow_yunxiao_task_closed", side_effect=fake_closed):
            result = advance_workflow("wf-close-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertTrue(result["advanced"])
        self.assertEqual(captured["event_type"], "yunxiao_workitem_close_skipped")
        self.assertEqual(captured["message"], "Yunxiao workitem already closed")
        self.assertTrue(captured["event_payload"]["alreadyClosed"])

    def test_advance_yunxiao_task_closed_skips_repeat(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = {**_workflow(), "status": "YUNXIAO_TASK_CLOSED"}
        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem"
        ) as close_workitem:
            result = advance_workflow("wf-close-1", WorkflowAdvanceRequest(operator="codex"))

        close_workitem.assert_not_called()
        self.assertFalse(result["advanced"])
        self.assertTrue(result["existing"])

    def test_advance_apifox_synced_without_explicit_close_ids_keeps_apifox_synced(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow
        from app.yunxiao import YunxiaoCloseSkipped

        workflow = _workflow()

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem",
            side_effect=YunxiaoCloseSkipped("Yunxiao explicit close task ids missing"),
        ), patch("app.workflow.db.mark_workflow_needs_human") as mark_needs_human, patch(
            "app.workflow.db.update_workflow_yunxiao_task_closed"
        ) as update_closed:
            result = advance_workflow("wf-close-1", WorkflowAdvanceRequest(operator="codex"))

        mark_needs_human.assert_not_called()
        update_closed.assert_not_called()
        self.assertFalse(result["advanced"])
        self.assertEqual(result["workflow"]["status"], "APIFOX_SYNCED")
        self.assertIn("explicit close task ids missing", result["reason"])

    def test_advance_apifox_synced_passes_request_close_task_refs(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = _workflow()

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem",
            return_value={
                "workitemIdentifier": "YX-1",
                "workitemDisplayId": "VEGZ-1186",
                "alreadyClosed": False,
                "closedStatus": "done",
                "closedStatusName": "已完成",
                "writeback": "success",
                "closedTaskIds": ["YX-1"],
                "skippedTaskIds": [],
                "configSource": "env",
            },
        ) as close_workitem, patch(
            "app.workflow.db.update_workflow_yunxiao_task_closed",
            return_value={**workflow, "status": "YUNXIAO_TASK_CLOSED"},
        ):
            result = advance_workflow(
                "wf-close-1",
                WorkflowAdvanceRequest(operator="codex", closeTaskRefs=["VEGZ-1186"]),
            )

        self.assertTrue(result["advanced"])
        close_workitem.assert_called_once_with(workflow, "codex", explicit_refs=["VEGZ-1186"])

    def test_advance_apifox_synced_close_failure_marks_needs_human(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import WorkflowError, advance_workflow
        from app.yunxiao import YunxiaoError

        workflow = _workflow()
        captured = {}

        def fake_needs_human(**kwargs):
            captured.update(kwargs)
            return {
                **workflow,
                "status": "NEEDS_HUMAN",
                "lastError": kwargs["error"],
                "retryCount": 1,
            }

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.close_yunxiao_workitem",
            side_effect=YunxiaoError("Yunxiao close config missing: done_status_id"),
        ), patch("app.workflow.db.mark_workflow_needs_human", side_effect=fake_needs_human):
            with self.assertRaises(WorkflowError) as raised:
                advance_workflow("wf-close-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertIn("Yunxiao workitem close failed", str(raised.exception))
        self.assertEqual(captured["from_status"], "APIFOX_SYNCED")
        self.assertEqual(captured["event_type"], "yunxiao_workitem_close_failed")
        self.assertEqual(captured["event_payload"]["yunxiaoTaskId"], "YX-1")


def _workflow() -> dict:
    return {
        "workflowId": "wf-close-1",
        "requirementKey": "REQ-1",
        "status": "APIFOX_SYNCED",
        "dingtalkUrl": "https://alidocs.dingtalk.com/i/nodes/node-123",
        "repoUrl": "https://codeup.example/repo.git",
        "branchName": "feature/REQ-1",
        "commitId": "abc123",
        "yunxiaoTaskId": "YX-1",
        "yunxiaoTaskDisplayId": "VEGZ-1186",
        "yunxiaoPipelineId": "pipe-1",
        "yunxiaoBuildNumber": "42",
        "apifoxProjectId": "8460173",
        "context": {
            "projectName": "jdb-school-crm",
            "requirement": {
                "summary": "新增客户跟进记录接口",
                "affectedRepos": ["jdb-school-crm"],
                "extra": {"access_key_secret": "secret-value"},
            },
            "codingResult": {
                "branchName": "feature/REQ-1",
                "commitId": "abc123",
                "mergeRequestUrl": "https://codeup.example/mr/1",
            },
            "yunxiao": {
                "createResult": {
                    "workitemIdentifier": "YX-1",
                    "workitemDisplayId": "VEGZ-1186",
                }
            },
            "pipeline": {
                    "pipelineId": "pipe-1",
                    "buildNumber": "42",
                    "branchName": "feature/REQ-1",
                    "commitId": "abc123",
                    "commitMessage": "feat: close selected task\n\n云效任务: VEGZ-1186",
                },
            "apifox": {
                "lastResult": {
                    "imported": True,
                    "projectId": "8460173",
                }
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
