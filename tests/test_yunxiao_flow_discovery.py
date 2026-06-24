import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import yunxiao_flow  # noqa: E402


class YunxiaoFlowDiscoveryTest(unittest.TestCase):
    def test_match_project_from_pipeline_repo_text(self) -> None:
        pipeline = {
            "data": {
                "name": "adapter-mvp Kubernetes 发布",
                "pipelineConfig": {
                    "sources": [
                        {
                            "data": {
                                "repo": "git@github.com:TomcatJM/adapter-mvp.git",
                                "label": "adapter-mvp",
                            }
                        }
                    ]
                },
            }
        }
        projects = [
            {"projectName": "jdb-order"},
            {"projectName": "adapter-mvp"},
        ]

        result = yunxiao_flow._match_project_from_pipeline(pipeline, projects)

        self.assertIsNotNone(result)
        self.assertEqual(result["projectName"], "adapter-mvp")

    def test_match_project_from_pipeline_ambiguous_returns_none(self) -> None:
        pipeline = {
            "data": {
                "name": "jdb-school release",
                "pipelineConfig": {"sources": [{"data": {"repo": "jdb-school-crm"}}]},
            }
        }
        projects = [
            {"projectName": "jdb-school"},
            {"projectName": "jdb-school-crm"},
        ]

        result = yunxiao_flow._match_project_from_pipeline(pipeline, projects)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
