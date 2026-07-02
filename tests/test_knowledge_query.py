import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch


MAIN_FILE = Path(__file__).resolve().parents[1] / "app" / "main.py"


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class KnowledgeQueryTest(unittest.TestCase):
    def test_query_knowledge_proxies_project_endpoint_and_normalizes_response(self) -> None:
        from app.knowledge import query_knowledge

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "answer": "线索创建先落 client，再补 track",
                    "developerEntrypoints": ["ClientController.add"],
                    "aiPlanHints": ["先看客户来源映射"],
                    "documents": [{"title": "线索流程"}],
                }
            )

        with patch(
            "app.knowledge.db.find_adapter_project_config",
            return_value={
                "projectKey": "jdb-school-crm",
                "knowledgeEndpoint": "http://kg.example.test/white/KnowledgeGraph/query",
            },
        ), patch("app.knowledge.urllib.request.urlopen", side_effect=fake_urlopen):
            result = query_knowledge(
                project_key="jdb-school-crm",
                question="创建线索逻辑是什么",
                mode="ai",
                timeout=12,
            )

        self.assertIn("question=%E5%88%9B%E5%BB%BA%E7%BA%BF%E7%B4%A2", captured["url"])
        self.assertIn("mode=ai", captured["url"])
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(result["projectKey"], "jdb-school-crm")
        self.assertEqual(result["businessAnswer"], "线索创建先落 client，再补 track")
        self.assertEqual(result["developerEntrypoints"], ["ClientController.add"])
        self.assertEqual(result["aiPlanHints"], ["先看客户来源映射"])
        self.assertEqual(result["documents"], [{"title": "线索流程"}])

    def test_query_knowledge_fails_when_project_is_not_configured(self) -> None:
        from app.knowledge import KnowledgeQueryError, query_knowledge

        with patch("app.knowledge.db.find_adapter_project_config", return_value=None):
            with self.assertRaises(KnowledgeQueryError) as raised:
                query_knowledge(project_key="missing", question="anything")

        self.assertEqual(str(raised.exception), "Adapter project config not found: missing")

    def test_knowledge_query_route_requires_adapter_token(self) -> None:
        module = ast.parse(MAIN_FILE.read_text(encoding="utf-8"))
        function = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "adapter_knowledge_query"
        )
        decorator = next(node for node in function.decorator_list if isinstance(node, ast.Call))

        self.assertEqual(ast.unparse(decorator.func), "app.post")
        self.assertEqual(ast.literal_eval(decorator.args[0]), "/adapter/knowledge/query")
        dependency = next(keyword for keyword in decorator.keywords if keyword.arg == "dependencies")
        self.assertEqual(ast.unparse(dependency.value.elts[0].func), "Depends")
        self.assertEqual(ast.unparse(dependency.value.elts[0].args[0]), "require_api_token")


if __name__ == "__main__":
    unittest.main()
