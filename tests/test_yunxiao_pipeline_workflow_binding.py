import unittest
from unittest.mock import patch

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ModuleNotFoundError:
    HAS_PYDANTIC = False


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class YunxiaoPipelineWorkflowBindingTest(unittest.TestCase):
    def test_success_with_workflow_id_marks_pipeline_success_and_apifox_synced(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "status": "CODE_SUBMITTED",
            "context": {"codingResult": {"summary": "done"}},
        }
        pipeline_success = {
            **workflow,
            "status": "PIPELINE_SUCCESS",
            "context": {
                "codingResult": {"summary": "done"},
                "pipeline": {"pipelineId": "pipe-1", "buildNumber": "88"},
            },
        }
        apifox_result = {
            "enabled": True,
            "imported": True,
            "reason": "Apifox import finished",
            "pipelineId": "pipe-1",
            "projectName": "jdb-school-gmc",
            "projectId": "apifox-1",
        }
        captured = {}

        def fake_pipeline_success(**kwargs):
            captured["pipeline_success"] = kwargs
            return pipeline_success

        def fake_apifox_synced(**kwargs):
            captured["apifox_synced"] = kwargs
            return {**pipeline_success, "status": "APIFOX_SYNCED", "apifoxProjectId": kwargs["apifox_project_id"]}

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-test-1",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            branchName="feature/wf-test-1",
            commitId="abc123",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", side_effect=fake_pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.update_workflow_apifox_synced", side_effect=fake_apifox_synced
        ):
            result = handle_pipeline_success({"globalParams": [{"key": "WORKFLOW_ID", "value": "wf-test-1"}]}, callback)

        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["workflow"]["status"], "APIFOX_SYNCED")
        self.assertEqual(captured["pipeline_success"]["from_status"], "CODE_SUBMITTED")
        self.assertEqual(captured["pipeline_success"]["pipeline_id"], "pipe-1")
        self.assertEqual(captured["apifox_synced"]["apifox_project_id"], "apifox-1")

    def test_success_without_workflow_id_keeps_apifox_import_but_does_not_bind(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}

        with patch("app.yunxiao_pipeline.db.find_workflow_instance") as find_workflow, patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ):
            result = handle_pipeline_success({}, callback)

        find_workflow.assert_not_called()
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["reason"], "missing WORKFLOW_ID")
        self.assertEqual(result["apifox"], apifox_result)

    def test_success_with_unknown_workflow_id_does_not_import_apifox(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-missing",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=None), patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event"
        ) as import_apifox:
            result = handle_pipeline_success({}, callback)

        import_apifox.assert_not_called()
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["reason"], "workflow not found")
        self.assertEqual(result["apifox"]["reason"], "workflow not found")

    def test_success_with_apifox_skipped_stays_pipeline_success(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {"workflowId": "wf-test-1", "status": "CODE_SUBMITTED", "context": {}}
        pipeline_success = {"workflowId": "wf-test-1", "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        captured = {}

        def fake_record(**kwargs):
            captured.update(kwargs)
            return {**pipeline_success, "lastError": kwargs["message"]}

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-test-1",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", side_effect=fake_record
        ), patch("app.yunxiao_pipeline.db.update_workflow_apifox_synced") as apifox_synced:
            result = handle_pipeline_success({}, callback)

        apifox_synced.assert_not_called()
        self.assertTrue(result["workflow"]["bound"])
        self.assertFalse(result["workflow"]["apifoxSynced"])
        self.assertEqual(result["workflow"]["workflow"]["status"], "PIPELINE_SUCCESS")
        self.assertEqual(captured["status"], "PIPELINE_SUCCESS")
        self.assertEqual(captured["event_type"], "apifox_sync_skipped")

    def test_failure_with_workflow_id_marks_pipeline_failed(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_failure

        workflow = {"workflowId": "wf-test-1", "status": "PIPELINE_RUNNING", "context": {}}
        analysis = {"summary": "test：单元测试失败", "category": "test_failure"}
        captured = {}

        def fake_failed(**kwargs):
            captured.update(kwargs)
            return {**workflow, "status": "PIPELINE_FAILED", "lastError": kwargs["error"]}

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-test-1",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="test",
            logTail="test failures",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_failed", side_effect=fake_failed
        ):
            result = handle_pipeline_failure(callback, analysis)

        self.assertTrue(result["bound"])
        self.assertEqual(result["workflow"]["status"], "PIPELINE_FAILED")
        self.assertEqual(captured["from_status"], "PIPELINE_RUNNING")
        self.assertEqual(captured["pipeline_id"], "pipe-1")
        self.assertEqual(captured["error"], "test：单元测试失败")


if __name__ == "__main__":
    unittest.main()
