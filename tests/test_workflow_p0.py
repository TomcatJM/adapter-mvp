import unittest
from unittest.mock import patch

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ModuleNotFoundError:
    HAS_PYDANTIC = False


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class WorkflowP0Test(unittest.TestCase):
    def test_start_workflow_creates_created_instance(self) -> None:
        from app.models import WorkflowStartRequest
        from app.workflow import start_workflow

        captured = {}

        def fake_create_workflow_instance(**kwargs):
            captured.update(kwargs)
            return {
                "workflowId": kwargs["workflow_id"],
                "status": "CREATED",
                "dingtalkUrl": kwargs["dingtalk_url"],
                "dingtalkNodeId": kwargs["dingtalk_node_id"],
                "context": kwargs["context"],
            }

        with patch("app.workflow._new_workflow_id", return_value="wf-test-1"), patch(
            "app.workflow.db.create_workflow_instance", side_effect=fake_create_workflow_instance
        ):
            result = start_workflow(
                WorkflowStartRequest(
                    dingtalkUrl="https://alidocs.dingtalk.com/i/nodes/node-123?utm_scene=team_space",
                    requirementKey="REQ-1",
                    operator="jzm",
                    context={"projectName": "jdb-school-gmc"},
                )
            )

        self.assertEqual(result["workflowId"], "wf-test-1")
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(captured["dingtalk_node_id"], "node-123")
        self.assertEqual(captured["context"]["projectName"], "jdb-school-gmc")
        self.assertEqual(captured["context"]["dingtalk"]["nodeId"], "node-123")

    def test_advance_created_reads_dingtalk_doc_and_updates_context(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.workflow import advance_workflow

        workflow = {
            "workflowId": "wf-test-1",
            "status": "CREATED",
            "dingtalkUrl": "https://alidocs.dingtalk.com/i/nodes/node-123",
            "dingtalkNodeId": "node-123",
            "context": {"dingtalk": {"url": "https://alidocs.dingtalk.com/i/nodes/node-123", "nodeId": "node-123"}},
        }
        doc = {
            "ok": True,
            "nodeId": "node-123",
            "workbookId": "book-1",
            "extension": "axls",
            "kind": "sheet",
            "configName": "default",
            "metadata": {"name": "需求表"},
            "sheets": [{"sheetId": "sheet-1", "name": "Sheet1"}],
            "sheetId": "sheet-1",
            "range": "A1:J50",
            "rangeResult": {"values": [["标题"]]},
        }
        captured = {}

        def fake_update(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": "DOC_READ", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.read_dingtalk_doc", return_value=doc
        ), patch("app.workflow.db.update_workflow_doc_read", side_effect=fake_update):
            result = advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertEqual(result["workflow"]["status"], "DOC_READ")
        self.assertEqual(captured["event_payload"]["kind"], "sheet")
        self.assertEqual(captured["context"]["dingtalk"]["read"]["sheetId"], "sheet-1")
        self.assertIn("requirement", result["nextAction"])

    def test_advance_created_records_retryable_error_without_terminal_failure(self) -> None:
        from app.models import WorkflowAdvanceRequest
        from app.dingtalk_docs import DingTalkDocError
        from app.workflow import WorkflowError, advance_workflow

        workflow = {
            "workflowId": "wf-test-1",
            "status": "CREATED",
            "dingtalkUrl": "https://alidocs.dingtalk.com/i/nodes/node-123",
            "dingtalkNodeId": "node-123",
            "context": {},
        }
        captured = {}

        def fake_record_error(**kwargs):
            captured.update(kwargs)
            return {**workflow, "lastError": kwargs["error"], "retryCount": 1}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.read_dingtalk_doc", side_effect=DingTalkDocError("token expired")
        ), patch("app.workflow.db.record_workflow_error", side_effect=fake_record_error):
            with self.assertRaises(WorkflowError):
                advance_workflow("wf-test-1", WorkflowAdvanceRequest(operator="codex"))

        self.assertEqual(captured["status"], "CREATED")
        self.assertEqual(captured["event_type"], "doc_read_failed")

    def test_submit_requirement_moves_doc_read_to_requirement_parsed(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import submit_requirement

        workflow = {"workflowId": "wf-test-1", "status": "DOC_READ", "context": {}}

        def fake_update(**kwargs):
            return {**workflow, "status": "REQUIREMENT_PARSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.update_workflow_requirement", side_effect=fake_update
        ):
            result = submit_requirement(
                "wf-test-1",
                WorkflowRequirementRequest(
                    summary="新增接口",
                    assigneeName="姬志猛",
                    acceptanceCriteria=["可创建"],
                    affectedRepos=["jdb-school-gmc"],
                    apiChanges=[{"method": "POST", "path": "/demo"}],
                ),
            )

        self.assertEqual(result["workflow"]["status"], "REQUIREMENT_PARSED")
        self.assertEqual(result["workflow"]["context"]["requirement"]["summary"], "新增接口")
        self.assertEqual(result["workflow"]["context"]["requirement"]["assigneeName"], "姬志猛")

    def test_submit_requirement_preserves_structured_demands(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import submit_requirement

        workflow = {"workflowId": "wf-test-2", "status": "DOC_READ", "context": {}}

        def fake_update(**kwargs):
            return {**workflow, "status": "REQUIREMENT_PARSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.update_workflow_requirement", side_effect=fake_update
        ):
            result = submit_requirement(
                "wf-test-2",
                WorkflowRequirementRequest(
                    documentTitle="校务3-1.adoc",
                    version="V1.0.0",
                    sourceUrl="https://alidocs.dingtalk.com/i/nodes/ndMj49yWjXn1ddY0cRLQpyZGJ3pmz5aA",
                    demands=[
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
                                    "contentLines": ["创建一条学生信息", "姓名必填", "手机号必填"],
                                }
                            ],
                        }
                    ],
                    summary=None,
                ),
            )

        requirement = result["workflow"]["context"]["requirement"]
        self.assertEqual(requirement["documentTitle"], "校务3-1.adoc")
        self.assertEqual(requirement["version"], "V1.0.0")
        self.assertEqual(requirement["sourceUrl"], "https://alidocs.dingtalk.com/i/nodes/ndMj49yWjXn1ddY0cRLQpyZGJ3pmz5aA")
        self.assertEqual(requirement["demands"][0]["demandIndex"], 1)
        self.assertEqual(requirement["demands"][0]["description"], "描述：1111111")
        self.assertEqual(requirement["demands"][0]["items"][0]["parentDemandIndex"], 1)
        self.assertEqual(requirement["demands"][0]["items"][0]["contentLines"][0], "创建一条学生信息")

    def test_submit_requirement_rejects_unknown_document_project_and_lists_yunxiao_projects(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import WorkflowError, submit_requirement

        workflow = {"workflowId": "wf-test-project", "status": "DOC_READ", "context": {}}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.find_yunxiao_project_config", return_value=None
        ), patch(
            "app.workflow.db.list_yunxiao_project_configs",
            return_value=[
                {"projectName": "01-校务系统"},
                {"projectName": "02-园务系统"},
            ],
        ), patch("app.workflow.db.update_workflow_requirement") as update:
            with self.assertRaises(WorkflowError) as raised:
                submit_requirement(
                    "wf-test-project",
                    WorkflowRequirementRequest(
                        documentTitle="需求模版.adoc",
                        version="V1.0.0",
                        extra={"sourceProjectName": "校务"},
                        demands=[
                            {
                                "demandIndex": 1,
                                "title": "需求一",
                                "items": [{"itemIndex": 1, "title": "任务一", "parentDemandTitle": "需求一"}],
                            }
                        ],
                    ),
                )

        message = str(raised.exception)
        self.assertIn("adapter_yunxiao_project_config", message)
        self.assertIn("projectName=校务", message)
        self.assertIn("01-校务系统", message)
        self.assertIn("02-园务系统", message)
        update.assert_not_called()

    def test_submit_requirement_rejects_when_structured_project_differs_from_dingtalk_read(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import WorkflowError, submit_requirement

        workflow = {
            "workflowId": "wf-test-project",
            "status": "DOC_READ",
            "context": {
                "dingtalk": {
                    "read": {
                        "document": {
                            "result": {
                                "data": [
                                    {
                                        "blockType": "paragraph",
                                        "paragraph": {"text": "项目名：园务"},
                                    }
                                ]
                            }
                        }
                    }
                }
            },
        }

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.update_workflow_requirement"
        ) as update:
            with self.assertRaises(WorkflowError) as raised:
                submit_requirement(
                    "wf-test-project",
                    WorkflowRequirementRequest(
                        documentTitle="需求模版.adoc",
                        version="V1.0.0",
                        extra={"sourceProjectName": "校务"},
                        demands=[
                            {
                                "demandIndex": 1,
                                "title": "需求一",
                                "items": [{"itemIndex": 1, "title": "任务一", "parentDemandTitle": "需求一"}],
                            }
                        ],
                    ),
                )

        message = str(raised.exception)
        self.assertIn("projectName mismatch", message)
        self.assertIn("readProjectName=园务", message)
        self.assertIn("submittedProjectName=校务", message)
        update.assert_not_called()

    def test_submit_requirement_uses_dingtalk_read_project_name_before_stale_context(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import submit_requirement

        workflow = {
            "workflowId": "wf-test-project",
            "status": "DOC_READ",
            "context": {
                "projectName": "01-校务系统",
                "dingtalk": {
                    "read": {
                        "document": {
                            "result": {
                                "data": [
                                    {
                                        "blockType": "paragraph",
                                        "paragraph": {"text": "项目名：02-园务系统"},
                                    }
                                ]
                            }
                        }
                    }
                },
            },
        }

        def fake_update(**kwargs):
            return {**workflow, "status": "REQUIREMENT_PARSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.find_yunxiao_project_config",
            return_value={"projectName": "02-园务系统", "projectConfigId": 10},
        ), patch("app.workflow.db.update_workflow_requirement", side_effect=fake_update):
            result = submit_requirement(
                "wf-test-project",
                WorkflowRequirementRequest(
                    documentTitle="需求模版.adoc",
                    version="V1.0.0",
                    demands=[
                        {
                            "demandIndex": 1,
                            "title": "需求一",
                            "items": [{"itemIndex": 1, "title": "任务一", "parentDemandTitle": "需求一"}],
                        }
                    ],
                ),
            )

        context = result["workflow"]["context"]
        self.assertEqual(context["projectName"], "02-园务系统")
        self.assertEqual(context["sourceProjectName"], "02-园务系统")

    def test_submit_requirement_uses_document_project_from_yunxiao_project_config(self) -> None:
        from app.models import WorkflowRequirementRequest
        from app.workflow import submit_requirement

        workflow = {"workflowId": "wf-test-project", "status": "DOC_READ", "context": {"projectName": "jdb-demo"}}

        def fake_update(**kwargs):
            return {**workflow, "status": "REQUIREMENT_PARSED", "context": kwargs["context"]}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.find_yunxiao_project_config",
            return_value={"projectName": "01-校务系统", "projectConfigId": 12},
        ), patch("app.workflow.db.update_workflow_requirement", side_effect=fake_update):
            result = submit_requirement(
                "wf-test-project",
                WorkflowRequirementRequest(
                    documentTitle="需求模版.adoc",
                    version="V1.0.0",
                    extra={"sourceProjectName": "01-校务系统"},
                    demands=[
                        {
                            "demandIndex": 1,
                            "title": "需求一",
                            "items": [{"itemIndex": 1, "title": "任务一", "parentDemandTitle": "需求一"}],
                        }
                    ],
                ),
            )

        context = result["workflow"]["context"]
        self.assertEqual(context["projectName"], "01-校务系统")
        self.assertEqual(context["sourceProjectName"], "01-校务系统")
        self.assertEqual(context["requirement"]["extra"]["sourceProjectName"], "01-校务系统")

    def test_submit_coding_result_moves_to_code_submitted(self) -> None:
        from app.models import WorkflowCodingResultRequest
        from app.workflow import submit_coding_result

        workflow = {"workflowId": "wf-test-1", "status": "REQUIREMENT_PARSED", "context": {}, "branchName": None}

        def fake_update(**kwargs):
            return {
                **workflow,
                "status": "CODE_SUBMITTED",
                "branchName": kwargs["branch_name"],
                "commitId": kwargs["commit_id"],
                "context": kwargs["context"],
            }

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.update_workflow_coding_result", side_effect=fake_update
        ):
            result = submit_coding_result(
                "wf-test-1",
                WorkflowCodingResultRequest(
                    branchName="feature/wf-test-1",
                    commitId="abc123",
                    mergeRequestUrl="https://example.invalid/mr/1",
                    summary="done",
                    tests=["unit ok"],
                ),
            )

        self.assertEqual(result["workflow"]["status"], "CODE_SUBMITTED")
        self.assertEqual(result["workflow"]["commitId"], "abc123")
        self.assertEqual(result["workflow"]["context"]["codingResult"]["tests"], ["unit ok"])

    def test_resolve_needs_human_to_apifox_synced(self) -> None:
        from app.models import WorkflowResolveRequest
        from app.workflow import resolve_workflow

        workflow = {"workflowId": "wf-test-1", "status": "NEEDS_HUMAN", "context": {}, "lastError": "close failed"}
        captured = {}

        def fake_resolve(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": kwargs["target_status"], "lastError": None}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.resolve_workflow_needs_human", side_effect=fake_resolve
        ):
            result = resolve_workflow(
                "wf-test-1",
                WorkflowResolveRequest(operator="codex", targetStatus="APIFOX_SYNCED", reason="AK configured"),
            )

        self.assertTrue(result["resolved"])
        self.assertEqual(result["workflow"]["status"], "APIFOX_SYNCED")
        self.assertEqual(captured["target_status"], "APIFOX_SYNCED")
        self.assertIn("retry Yunxiao close", result["nextAction"])

    def test_resolve_rejects_unsupported_target(self) -> None:
        from app.models import WorkflowResolveRequest
        from app.workflow import WorkflowError, resolve_workflow

        workflow = {"workflowId": "wf-test-1", "status": "NEEDS_HUMAN", "context": {}}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.resolve_workflow_needs_human"
        ) as db_resolve:
            with self.assertRaises(WorkflowError) as raised:
                resolve_workflow(
                    "wf-test-1",
                    WorkflowResolveRequest(operator="codex", targetStatus="CREATED", reason="bad target"),
                )

        db_resolve.assert_not_called()
        self.assertIn("Unsupported resolve targetStatus", str(raised.exception))

    def test_retry_pipeline_failed_to_coding_requested(self) -> None:
        from app.models import WorkflowRetryRequest
        from app.workflow import retry_workflow

        workflow = {
            "workflowId": "wf-test-1",
            "status": "PIPELINE_FAILED",
            "context": {},
            "lastError": "unit test failed",
            "retryCount": 1,
        }
        captured = {}

        def fake_retry(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": kwargs["target_status"], "lastError": None, "retryCount": 2}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.retry_workflow_from_pipeline_failed", side_effect=fake_retry
        ):
            result = retry_workflow(
                "wf-test-1",
                WorkflowRetryRequest(operator="codex", reason="fix flaky test", maxRetryCount=3),
            )

        self.assertTrue(result["retried"])
        self.assertEqual(result["workflow"]["status"], "CODING_REQUESTED")
        self.assertEqual(captured["target_status"], "CODING_REQUESTED")
        self.assertEqual(captured["max_retry_count"], 3)
        self.assertIn("coding-result", result["nextAction"])

    def test_retry_rejects_non_pipeline_failed_status(self) -> None:
        from app.models import WorkflowRetryRequest
        from app.workflow import WorkflowError, retry_workflow

        workflow = {"workflowId": "wf-test-1", "status": "NEEDS_HUMAN", "context": {}, "retryCount": 1}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.retry_workflow_from_pipeline_failed"
        ) as db_retry:
            with self.assertRaises(WorkflowError) as raised:
                retry_workflow("wf-test-1", WorkflowRetryRequest(operator="codex", reason="try again"))

        db_retry.assert_not_called()
        self.assertIn("Workflow status is not PIPELINE_FAILED", str(raised.exception))

    def test_retry_rejects_when_retry_count_exceeds_limit(self) -> None:
        from app.models import WorkflowRetryRequest
        from app.workflow import WorkflowError, retry_workflow

        workflow = {"workflowId": "wf-test-1", "status": "PIPELINE_FAILED", "context": {}, "retryCount": 3}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.retry_workflow_from_pipeline_failed"
        ) as db_retry:
            with self.assertRaises(WorkflowError) as raised:
                retry_workflow(
                    "wf-test-1",
                    WorkflowRetryRequest(operator="codex", reason="retry limit", maxRetryCount=3),
                )

        db_retry.assert_not_called()
        self.assertIn("retry count exceeded limit", str(raised.exception))

    def test_retry_rejects_unsupported_target_status(self) -> None:
        from app.models import WorkflowRetryRequest
        from app.workflow import WorkflowError, retry_workflow

        workflow = {"workflowId": "wf-test-1", "status": "PIPELINE_FAILED", "context": {}, "retryCount": 1}

        with patch("app.workflow.db.find_workflow_instance", return_value=workflow), patch(
            "app.workflow.db.retry_workflow_from_pipeline_failed"
        ) as db_retry:
            with self.assertRaises(WorkflowError) as raised:
                retry_workflow(
                    "wf-test-1",
                    WorkflowRetryRequest(operator="codex", targetStatus="PIPELINE_SUCCESS", reason="bad target"),
                )

        db_retry.assert_not_called()
        self.assertIn("Unsupported retry targetStatus", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
