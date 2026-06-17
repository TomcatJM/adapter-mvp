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
                    acceptanceCriteria=["可创建"],
                    affectedRepos=["jdb-school-gmc"],
                    apiChanges=[{"method": "POST", "path": "/demo"}],
                ),
            )

        self.assertEqual(result["workflow"]["status"], "REQUIREMENT_PARSED")
        self.assertEqual(result["workflow"]["context"]["requirement"]["summary"], "新增接口")

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


if __name__ == "__main__":
    unittest.main()
