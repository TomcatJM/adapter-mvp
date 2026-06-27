import unittest
from unittest.mock import patch

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ModuleNotFoundError:
    HAS_PYDANTIC = False


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class YunxiaoPipelineWorkflowBindingTest(unittest.TestCase):
    def test_running_with_workflow_id_marks_pipeline_running(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_running

        workflow = {"workflowId": "wf-test-1", "status": "CODE_SUBMITTED", "context": {}}
        captured = {}

        def fake_running(**kwargs):
            captured.update(kwargs)
            return {
                **workflow,
                "status": "PIPELINE_RUNNING",
                "context": {"pipeline": {"pipelineId": kwargs["pipeline_id"], "buildNumber": kwargs["build_number"]}},
            }

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-test-1",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="build",
            branchName="feature/wf-test-1",
            commitId="abc123",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_running", side_effect=fake_running
        ):
            result = handle_pipeline_running(callback)

        self.assertTrue(result["bound"])
        self.assertTrue(result["advanced"])
        self.assertEqual(result["bindingSource"], "workflow_id")
        self.assertEqual(result["workflow"]["status"], "PIPELINE_RUNNING")
        self.assertEqual(captured["pipeline_id"], "pipe-1")
        self.assertEqual(captured["build_number"], "88")

    def test_running_with_existing_pipeline_running_is_idempotent(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_running

        workflow = {"workflowId": "wf-test-1", "status": "PIPELINE_RUNNING", "context": {}}
        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-REQ-1-88",
            workflowId="wf-test-1",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="build",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_running"
        ) as update_running:
            result = handle_pipeline_running(callback)

        update_running.assert_not_called()
        self.assertTrue(result["bound"])
        self.assertFalse(result["advanced"])
        self.assertEqual(result["reason"], "workflow already PIPELINE_RUNNING")

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

    def test_success_without_workflow_id_or_match_keeps_apifox_import_but_does_not_bind(self) -> None:
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
            "app.yunxiao_pipeline.db.find_workflow_by_pipeline_build", return_value=None
        ) as find_pipeline, patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ):
            result = handle_pipeline_success({}, callback)

        find_workflow.assert_not_called()
        find_pipeline.assert_called_once_with("pipe-1", "88")
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["reason"], "workflow not matched")
        self.assertEqual(result["apifox"], apifox_result)

    def test_success_without_workflow_id_binds_by_yunxiao_task_id(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "YX-1",
            "status": "CODE_SUBMITTED",
            "context": {},
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {
            "enabled": True,
            "imported": True,
            "reason": "Apifox import finished",
            "pipelineId": "pipe-1",
            "projectId": "apifox-1",
        }

        callback = YunxiaoPipelineFailureCallback(
            taskId="rel-YX-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=workflow) as find_task, patch(
            "app.yunxiao_pipeline.db.find_workflow_by_pipeline_build"
        ) as find_pipeline, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ), patch(
            "app.yunxiao_pipeline.db.update_workflow_apifox_synced",
            return_value={**pipeline_success, "status": "APIFOX_SYNCED", "apifoxProjectId": "apifox-1"},
        ):
            result = handle_pipeline_success(
                {"globalParams": [{"key": "REQUIREMENT_ID", "value": "YX-1"}]},
                callback,
            )

        find_task.assert_called_once_with("YX-1")
        find_pipeline.assert_not_called()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["status"], "APIFOX_SYNCED")

    def test_success_without_workflow_id_does_not_import_when_match_is_ambiguous(self) -> None:
        from app import db
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch(
            "app.yunxiao_pipeline.db.find_workflow_by_pipeline_build",
            side_effect=db.WorkflowLookupAmbiguousError("Multiple workflow instances matched"),
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event") as import_apifox:
            result = handle_pipeline_success({}, callback)

        import_apifox.assert_not_called()
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "pipeline_build")
        self.assertEqual(result["workflow"]["reason"], "workflow match ambiguous")
        self.assertEqual(result["apifox"]["reason"], "workflow match ambiguous")

    def test_success_binds_by_workflow_id_in_commit_message(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {"workflowId": "wf-test-1", "status": "CODE_SUBMITTED", "context": {}}
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 创建学生信息\n\nWORKFLOW_ID=wf-test-1\nYUNXIAO_TASK_ID=YX-1",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_instance", return_value=workflow) as find_workflow, patch(
            "app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id"
        ) as find_task, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        find_workflow.assert_called_once_with("wf-test-1")
        find_task.assert_not_called()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_workflow_id")

    def test_success_binds_by_yunxiao_task_id_in_commit_title(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {"workflowId": "wf-test-1", "yunxiaoTaskId": "YX-1", "status": "CODING_REQUESTED", "context": {}}
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 验证链路 YUNXIAO_TASK_ID=YX-1",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=workflow) as find_task, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        find_task.assert_called_once_with("YX-1")
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["status"], "PIPELINE_SUCCESS")

    def test_success_refreshes_pipeline_context_when_workflow_already_apifox_synced(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "YX-1",
            "status": "APIFOX_SYNCED",
            "context": {"pipeline": {"pipelineId": "pipe-1", "buildNumber": "87"}},
        }
        captured = {}

        def fake_record(**kwargs):
            captured.update(kwargs)
            return {**workflow, "context": kwargs["context"]}

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            branchName="develop",
            commitId="abc123",
            commitMessage="feat: 验证链路\n\n云效任务: VEGZ-1186",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=workflow), patch(
            "app.yunxiao_pipeline.db.record_workflow_context_event", side_effect=fake_record
        ) as record_result:
            result = handle_pipeline_success({}, callback)

        record_result.assert_called_once()
        self.assertFalse(result["workflow"]["advanced"])
        self.assertEqual(captured["status"], "APIFOX_SYNCED")
        self.assertEqual(captured["event_type"], "pipeline_success_context_refreshed")
        self.assertEqual(captured["context"]["pipeline"]["buildNumber"], "88")
        self.assertEqual(captured["context"]["pipeline"]["commitMessage"], "feat: 验证链路\n\n云效任务: VEGZ-1186")

    def test_success_binds_by_yunxiao_display_id_in_commit_title(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
            "yunxiaoTaskDisplayId": "VEGZ-1186",
            "status": "CODING_REQUESTED",
            "context": {
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "8ce853ae60df1fa6200ae2728d",
                        "workitemDisplayId": "VEGZ-1186",
                    }
                }
            },
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 验证链路 YUNXIAO_TASK_ID=VEGZ-1186",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        find_task.assert_called_once_with("VEGZ-1186")
        list_workflows.assert_called_once()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_yunxiao_display_id_alias_in_commit_title(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
            "yunxiaoTaskDisplayId": "VEGZ-1186",
            "status": "CODING_REQUESTED",
            "context": {"yunxiao": {"createResult": {"workitemDisplayId": "VEGZ-1186"}}},
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 验证链路 YUNXIAO_TASK_DISPLAY_ID=VEGZ-1186",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        find_task.assert_called_once_with("VEGZ-1186")
        list_workflows.assert_called_once()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_chinese_yunxiao_display_id_alias_in_commit_message(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
            "yunxiaoTaskDisplayId": "VEGZ-1186",
            "status": "CODING_REQUESTED",
            "context": {"yunxiao": {"createResult": {"serialNumber": "VEGZ-1186"}}},
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 验证链路\n\n云效展示ID：VEGZ-1186",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        find_task.assert_called_once_with("VEGZ-1186")
        list_workflows.assert_called_once()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_any_child_task_display_id_when_commit_lists_multiple_yunxiao_tasks(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "REQ-ROOT",
            "yunxiaoTaskDisplayId": "AYRR-4057",
            "status": "CODING_REQUESTED",
            "context": {
                "yunxiao": {
                    "createResult": {
                        "workitemIdentifier": "REQ-ROOT",
                        "workitemDisplayId": "AYRR-4057",
                        "demands": [
                            {
                                "workitemIdentifier": "REQ-1",
                                "workitemDisplayId": "AYRR-4057",
                                "items": [
                                    {
                                        "workitemIdentifier": "TASK-1",
                                        "workitemDisplayId": "AYRR-4063",
                                    },
                                    {
                                        "workitemIdentifier": "TASK-2",
                                        "serialNumber": "AYRR-4065",
                                    },
                                ],
                            }
                        ],
                    }
                }
            },
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 验证链路\n\n云效任务: AYRR-4062、 AYRR-4063、 AYRR-4064",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success({}, callback)

        self.assertEqual(find_task.call_count, 2)
        self.assertEqual([call.args[0] for call in find_task.call_args_list], ["AYRR-4062", "AYRR-4063"])
        self.assertEqual(list_workflows.call_count, 2)
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_loose_chinese_yunxiao_key_in_commit_message(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        for commit_message in (
            "feat: 验证链路 云效id=VEGZ-1186",
            "feat: 验证链路\n\n云效任务：VEGZ-1186",
        ):
            with self.subTest(commit_message=commit_message):
                workflow = {
                    "workflowId": "wf-test-1",
                    "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
                    "yunxiaoTaskDisplayId": "VEGZ-1186",
                    "status": "CODING_REQUESTED",
                    "context": {"yunxiao": {"createResult": {"workitemDisplayId": "VEGZ-1186"}}},
                }
                pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
                apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
                callback = YunxiaoPipelineFailureCallback(
                    taskId="yx-flow-pipe-1-88",
                    pipelineId="pipe-1",
                    buildNumber="88",
                    stageName="release",
                    commitMessage=commit_message,
                )

                with patch(
                    "app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id",
                    return_value=None,
                ) as find_task, patch(
                    "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
                ) as list_workflows, patch(
                    "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
                ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
                    "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
                ):
                    result = handle_pipeline_success({}, callback)

                find_task.assert_called_once_with("VEGZ-1186")
                list_workflows.assert_called_once()
                self.assertTrue(result["workflow"]["bound"])
                self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
                self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_yunxiao_display_id_global_param_alias(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
            "yunxiaoTaskDisplayId": "VEGZ-1186",
            "status": "CODING_REQUESTED",
            "context": {"yunxiao": {"createResult": {"workitemDisplayId": "VEGZ-1186"}}},
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success(
                {"globalParams": [{"key": "YUNXIAO_TASK_DISPLAY_ID", "value": "VEGZ-1186"}]},
                callback,
            )

        find_task.assert_called_once_with("VEGZ-1186")
        list_workflows.assert_called_once()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_success_binds_by_loose_chinese_yunxiao_global_param(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "yunxiaoTaskId": "8ce853ae60df1fa6200ae2728d",
            "yunxiaoTaskDisplayId": "VEGZ-1186",
            "status": "CODING_REQUESTED",
            "context": {"yunxiao": {"createResult": {"workitemDisplayId": "VEGZ-1186"}}},
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None) as find_task, patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result), patch(
            "app.yunxiao_pipeline.db.record_workflow_apifox_result", return_value=pipeline_success
        ):
            result = handle_pipeline_success(
                {"globalParams": [{"key": "云效任务", "value": "VEGZ-1186"}]},
                callback,
            )

        find_task.assert_called_once_with("VEGZ-1186")
        list_workflows.assert_called_once()
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "yunxiao_task_id")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-test-1")

    def test_failure_binds_by_yunxiao_task_id_in_commit_message(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_failure

        workflow = {"workflowId": "wf-test-1", "yunxiaoTaskId": "YX-1", "status": "CODE_SUBMITTED", "context": {}}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="build",
            commitMessage="fix: 修复学生信息校验\n\n云效任务ID：YX-1",
            logTail="build failed",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=workflow) as find_task, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_failed",
            return_value={**workflow, "status": "PIPELINE_FAILED", "lastError": "build failed"},
        ):
            result = handle_pipeline_failure(callback, {"summary": "build failed"})

        find_task.assert_called_once_with("YX-1")
        self.assertTrue(result["bound"])
        self.assertEqual(result["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["status"], "PIPELINE_FAILED")

    def test_commit_message_task_id_not_found_stops_binding(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
            commitMessage="feat: 创建学生信息\n\nYUNXIAO_TASK_ID=YX-MISSING",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_yunxiao_task_id", return_value=None), patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[]
        ), patch(
            "app.yunxiao_pipeline.db.find_workflow_by_pipeline_build"
        ) as find_pipeline, patch("app.yunxiao_pipeline.maybe_import_from_flow_event") as import_apifox:
            result = handle_pipeline_success({}, callback)

        find_pipeline.assert_not_called()
        import_apifox.assert_not_called()
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "commit_message_yunxiao_task_id")
        self.assertEqual(result["workflow"]["reason"], "workflow not found")
        self.assertEqual(result["apifox"]["reason"], "workflow not found")

    def test_success_without_workflow_id_binds_by_unique_active_project_workflow(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-test-1",
            "status": "CODE_SUBMITTED",
            "context": {
                "yunxiao": {"createResult": {"projectName": "校CRM"}},
                "requirement": {"affectedRepos": []},
            },
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS", "context": {"pipeline": {}}}
        apifox_result = {
            "enabled": True,
            "imported": True,
            "reason": "Apifox import finished",
            "pipelineId": "pipe-1",
            "projectId": "apifox-1",
        }

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_pipeline_build", return_value=None), patch(
            "app.yunxiao_pipeline.db.find_apifox_pipeline_config",
            return_value={"pipelineId": "pipe-1", "projectName": "jdb-school-crm"},
        ), patch(
            "app.yunxiao_pipeline.db.find_yunxiao_project_config",
            return_value={"projectName": "jdb-school-crm", "organizationId": "org-1", "projectId": "space-1"},
        ), patch(
            "app.yunxiao_pipeline.db.list_yunxiao_project_configs",
            return_value=[
                {"projectName": "jdb-school-crm", "organizationId": "org-1", "projectId": "space-1"},
                {"projectName": "校CRM", "organizationId": "org-1", "projectId": "space-1"},
            ],
        ), patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ) as list_workflows, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ), patch(
            "app.yunxiao_pipeline.db.update_workflow_apifox_synced",
            return_value={**pipeline_success, "status": "APIFOX_SYNCED", "apifoxProjectId": "apifox-1"},
        ):
            result = handle_pipeline_success({}, callback)

        list_workflows.assert_called_once()
        self.assertEqual(
            set(list_workflows.call_args.args[0]),
            {"CODING_REQUESTED", "CODE_SUBMITTED", "PIPELINE_RUNNING", "PIPELINE_SUCCESS"},
        )
        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "project_active_workflow")
        self.assertEqual(result["workflow"]["workflow"]["status"], "APIFOX_SYNCED")

    def test_success_without_workflow_id_does_not_bind_when_project_workflow_is_ambiguous(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflows = [
            {"workflowId": "wf-test-1", "status": "CODE_SUBMITTED", "context": {"projectName": "jdb-school-crm"}},
            {"workflowId": "wf-test-2", "status": "PIPELINE_RUNNING", "context": {"projectName": "jdb-school-crm"}},
        ]
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="release",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_pipeline_build", return_value=None), patch(
            "app.yunxiao_pipeline.db.find_apifox_pipeline_config",
            return_value={"pipelineId": "pipe-1", "projectName": "jdb-school-crm"},
        ), patch("app.yunxiao_pipeline.db.find_yunxiao_project_config", return_value=None), patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=workflows
        ), patch("app.yunxiao_pipeline.maybe_import_from_flow_event") as import_apifox:
            result = handle_pipeline_success({}, callback)

        import_apifox.assert_not_called()
        self.assertFalse(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "project_active_workflow")
        self.assertEqual(result["workflow"]["reason"], "workflow match ambiguous")
        self.assertEqual(result["apifox"]["reason"], "workflow match ambiguous")

    def test_success_binds_project_active_workflow_by_requirement_extra_project_alias(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_success

        workflow = {
            "workflowId": "wf-garden-1",
            "status": "CODE_SUBMITTED",
            "context": {
                "requirement": {
                    "extra": {
                        "documentProjectName": "园务",
                        "sourceProjectName": "园务",
                    }
                }
            },
        }
        pipeline_success = {**workflow, "status": "PIPELINE_SUCCESS"}
        apifox_result = {"enabled": True, "imported": True, "projectId": "apifox-1", "reason": "Apifox import finished"}
        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-4744934-336",
            pipelineId="4744934",
            buildNumber="336",
            stageName="release",
            branchName="develop",
            commitId="merge-commit",
            commitMessage="Merge branch 'hotfix/0626' into develop",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_pipeline_build", return_value=None), patch(
            "app.yunxiao_pipeline.db.find_workflow_by_branch_commit", return_value=None
        ), patch(
            "app.yunxiao_pipeline.db.find_apifox_pipeline_config",
            return_value={"pipelineId": "4744934", "projectName": "园CRM"},
        ), patch(
            "app.yunxiao_pipeline.db.find_yunxiao_project_config",
            return_value={"projectName": "园CRM", "organizationId": "org-1", "projectId": "garden-1"},
        ), patch(
            "app.yunxiao_pipeline.db.list_yunxiao_project_configs",
            return_value=[
                {"projectName": "园CRM", "organizationId": "org-1", "projectId": "garden-1"},
                {"projectName": "园务", "organizationId": "org-1", "projectId": "garden-1"},
            ],
        ), patch(
            "app.yunxiao_pipeline.db.list_workflows_by_statuses", return_value=[workflow]
        ), patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_success", return_value=pipeline_success
        ), patch(
            "app.yunxiao_pipeline.maybe_import_from_flow_event", return_value=apifox_result
        ), patch(
            "app.yunxiao_pipeline.db.update_workflow_apifox_synced",
            return_value={**pipeline_success, "status": "APIFOX_SYNCED", "apifoxProjectId": "apifox-1"},
        ):
            result = handle_pipeline_success({}, callback)

        self.assertTrue(result["workflow"]["bound"])
        self.assertEqual(result["workflow"]["bindingSource"], "project_active_workflow")
        self.assertEqual(result["workflow"]["workflow"]["workflowId"], "wf-garden-1")
        self.assertEqual(result["workflow"]["workflow"]["status"], "APIFOX_SYNCED")

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

    def test_failure_without_workflow_id_binds_by_branch_commit(self) -> None:
        from app.models import YunxiaoPipelineFailureCallback
        from app.yunxiao_pipeline import handle_pipeline_failure

        workflow = {
            "workflowId": "wf-test-1",
            "status": "CODE_SUBMITTED",
            "branchName": "feature/wf-test-1",
            "commitId": "abc123",
            "context": {},
        }
        analysis = {"summary": "build：构建失败", "category": "build_failure"}

        callback = YunxiaoPipelineFailureCallback(
            taskId="yx-flow-pipe-1-88",
            pipelineId="pipe-1",
            buildNumber="88",
            stageName="build",
            branchName="feature/wf-test-1",
            commitId="abc123",
            logTail="build failed",
        )

        with patch("app.yunxiao_pipeline.db.find_workflow_by_pipeline_build", return_value=None), patch(
            "app.yunxiao_pipeline.db.find_workflow_by_branch_commit", return_value=workflow
        ) as find_branch_commit, patch(
            "app.yunxiao_pipeline.db.update_workflow_pipeline_failed",
            return_value={**workflow, "status": "PIPELINE_FAILED", "lastError": "build：构建失败"},
        ):
            result = handle_pipeline_failure(callback, analysis)

        find_branch_commit.assert_called_once_with("feature/wf-test-1", "abc123")
        self.assertTrue(result["bound"])
        self.assertEqual(result["bindingSource"], "branch_commit")
        self.assertEqual(result["workflow"]["status"], "PIPELINE_FAILED")

    def test_normalize_flow_event_extracts_branch_commit_from_task_and_global_params(self) -> None:
        from app.main import _normalize_flow_event

        callback = _normalize_flow_event(
            {
                "task": {
                    "pipelineId": "pipe-1",
                    "buildNumber": "88",
                    "stageName": "build",
                    "taskName": "compile",
                    "branchName": "feature/wf-test-1",
                },
                "globalParams": [
                    {"key": "TASK_ID", "value": "rel-YX-1-88"},
                    {"key": "WORKFLOW_ID", "value": "wf-test-1"},
                    {"key": "COMMIT_ID", "value": "abc123"},
                    {"key": "COMMIT_MESSAGE", "value": "feat: 创建学生信息\n\nWORKFLOW_ID=wf-test-1"},
                    {"key": "BUILD_USER", "value": "tester"},
                ],
            }
        )

        self.assertEqual(callback.task_id, "rel-YX-1-88")
        self.assertEqual(callback.workflow_id, "wf-test-1")
        self.assertEqual(callback.pipeline_id, "pipe-1")
        self.assertEqual(callback.build_number, "88")
        self.assertEqual(callback.branch_name, "feature/wf-test-1")
        self.assertEqual(callback.commit_id, "abc123")
        self.assertEqual(callback.commit_message, "feat: 创建学生信息\n\nWORKFLOW_ID=wf-test-1")
        self.assertEqual(callback.operator, "tester")

    def test_normalize_flow_event_uses_ci_commit_title_as_message_fallback(self) -> None:
        from app.main import _normalize_flow_event

        callback = _normalize_flow_event(
            {
                "task": {
                    "pipelineId": "4957185",
                    "buildNumber": "24",
                    "stageName": "命令",
                    "taskName": "执行命令",
                },
                "globalParams": [
                    {"key": "CI_COMMIT_TITLE", "value": "feat: 验证链路 YUNXIAO_TASK_ID=YX-1"},
                ],
            }
        )

        self.assertEqual(callback.commit_message, "feat: 验证链路 YUNXIAO_TASK_ID=YX-1")

    def test_normalize_flow_event_extracts_nested_yunxiao_source_data(self) -> None:
        from app.main import _normalize_flow_event

        callback = _normalize_flow_event(
            {
                "task": {
                    "pipelineId": "4957185",
                    "buildNumber": "24",
                    "stageName": "命令",
                    "taskName": "执行命令",
                    "statusCode": "SUCCESS",
                },
                "sources": [
                    {
                        "name": "jdb-demo_6e65",
                        "type": "codeup",
                        "data": {
                            "repo": "https://codeup.aliyun.com/example/jdb-demo.git",
                            "branch": "develop",
                            "commitId": "abc123",
                            "commitMsg": (
                                "[{\"commitAuthor\":\"tester\","
                                "\"commitMsg\":\"feat%3A%20demo%5Cn%5CnWORKFLOW_ID%3Dwf-test-1%5CnYUNXIAO_TASK_ID%3DYX-1\","
                                "\"commitId\":\"abc123\"}]"
                            ),
                        },
                    }
                ],
            }
        )

        self.assertEqual(callback.pipeline_id, "4957185")
        self.assertEqual(callback.build_number, "24")
        self.assertEqual(callback.branch_name, "develop")
        self.assertEqual(callback.commit_id, "abc123")
        self.assertEqual(callback.commit_message, "feat: demo\n\nWORKFLOW_ID=wf-test-1\nYUNXIAO_TASK_ID=YX-1")

    def test_flow_event_running_status_advances_workflow(self) -> None:
        from app.main import _handle_flow_event

        callback_result = {
            "bound": True,
            "advanced": True,
            "bindingSource": "workflow_id",
            "workflow": {"workflowId": "wf-test-1", "status": "PIPELINE_RUNNING"},
        }

        with patch("app.main.handle_pipeline_running", return_value=callback_result):
            result = _handle_flow_event(
                {
                    "task": {
                        "statusCode": "RUNNING",
                        "pipelineId": "pipe-1",
                        "buildNumber": "88",
                        "stageName": "build",
                        "taskName": "compile",
                    },
                    "globalParams": [
                        {"key": "WORKFLOW_ID", "value": "wf-test-1"},
                        {"key": "TASK_ID", "value": "rel-REQ-1-88"},
                    ],
                }
            )

        self.assertEqual(result["mode"], "flow_event")
        self.assertEqual(result["statusCode"], "RUNNING")
        self.assertEqual(result["workflow"]["workflow"]["status"], "PIPELINE_RUNNING")


if __name__ == "__main__":
    unittest.main()
