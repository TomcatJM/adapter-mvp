import unittest
from unittest.mock import patch

try:
    import pydantic  # noqa: F401

    HAS_PYDANTIC = True
except ModuleNotFoundError:
    HAS_PYDANTIC = False


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is not installed")
class YunxiaoDeleteRouteTest(unittest.TestCase):
    def test_delete_request_workflow_uses_get_workflow_result_directly(self) -> None:
        from app.main import _delete_request_workflow
        from app.models import YunxiaoWorkitemDeleteRequest

        workflow = {"workflowId": "wf-1", "context": {"projectName": "jdb-demo"}}
        request = YunxiaoWorkitemDeleteRequest(workflowId="wf-1")

        with patch("app.main.get_workflow", return_value=workflow):
            result = _delete_request_workflow(request)

        self.assertEqual(result, workflow)


if __name__ == "__main__":
    unittest.main()
