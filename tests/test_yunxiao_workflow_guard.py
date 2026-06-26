import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.yunxiao_guard import (
    YunxiaoWorkflowGuardError,
    assert_yunxiao_close_plan_valid,
    assert_yunxiao_create_result_valid,
)


ROOT = Path(__file__).resolve().parents[1]


class YunxiaoWorkflowGuardTest(unittest.TestCase):
    def test_valid_requirement_tree_passes_create_and_close_guard(self) -> None:
        workflow = _workflow_with_valid_tree()

        assert_yunxiao_create_result_valid(workflow)
        assert_yunxiao_close_plan_valid(workflow)

    def test_create_guard_requires_task_parent_and_sprint_when_version_exists(self) -> None:
        workflow = _workflow_with_valid_tree()
        task = workflow["context"]["yunxiao"]["createResult"]["demands"][0]["items"][0]
        task["parentIdentifier"] = "WRONG-REQ"
        task["sprintId"] = ""

        with self.assertRaises(YunxiaoWorkflowGuardError) as raised:
            assert_yunxiao_create_result_valid(workflow)

        message = str(raised.exception)
        self.assertIn("parentIdentifier must equal parent demand id", message)
        self.assertIn("sprintId is required", message)

    def test_create_guard_requires_demand_details_not_only_count(self) -> None:
        workflow = _workflow_with_valid_tree()
        workflow["context"]["yunxiao"]["createResult"]["demands"] = []

        with self.assertRaises(YunxiaoWorkflowGuardError) as raised:
            assert_yunxiao_create_result_valid(workflow)

        self.assertIn("demands detail", str(raised.exception))

    def test_close_guard_rejects_requirement_tree_without_child_task_ids(self) -> None:
        workflow = _workflow_with_valid_tree()
        workflow["context"]["yunxiao"]["createResult"]["taskIdentifiers"] = []

        with self.assertRaises(YunxiaoWorkflowGuardError) as raised:
            assert_yunxiao_close_plan_valid(workflow)

        self.assertIn("child task ids", str(raised.exception))

    def test_cli_validates_workflow_json_file(self) -> None:
        workflow = _workflow_with_valid_tree()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(workflow, handle, ensure_ascii=False)
            path = handle.name
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate_yunxiao_workflow_guard.py"),
                    "--file",
                    path,
                    "--mode",
                    "all",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("guard passed", result.stdout)


def _workflow_with_valid_tree() -> dict:
    return {
        "workflowId": "wf-guard-1",
        "yunxiaoTaskId": "REQ-1",
        "context": {
            "requirement": {
                "summary": "需求模版",
                "version": "V1.0.0",
                "demands": [
                    {
                        "demandIndex": 1,
                        "title": "需求一",
                        "items": [
                            {
                                "itemIndex": 1,
                                "title": "任务一",
                                "contentLines": ["主要内容"],
                            }
                        ],
                    }
                ],
            },
            "yunxiao": {
                "createResult": {
                    "workitemIdentifier": "REQ-1",
                    "category": "Req",
                    "sprintId": "sprint-1",
                    "demandCount": 1,
                    "taskCount": 1,
                    "taskIdentifiers": ["TASK-1"],
                    "demands": [
                        {
                            "demandIndex": 1,
                            "title": "需求一",
                            "workitemIdentifier": "REQ-1",
                            "category": "Req",
                            "sprintId": "sprint-1",
                            "items": [
                                {
                                    "itemIndex": 1,
                                    "title": "任务一",
                                    "workitemIdentifier": "TASK-1",
                                    "category": "Task",
                                    "parentIdentifier": "REQ-1",
                                    "sprintId": "sprint-1",
                                }
                            ],
                        }
                    ],
                }
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
