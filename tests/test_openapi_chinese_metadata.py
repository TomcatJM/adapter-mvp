import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class OpenapiChineseMetadataTest(unittest.TestCase):
    def test_public_routes_have_chinese_summary_and_tags(self) -> None:
        tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
        routes: dict[str, dict[str, object]] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not _is_app_route(decorator):
                    continue
                route_path = _route_path(decorator)
                if not route_path:
                    continue
                routes[route_path] = {
                    "summary": _keyword_value(decorator, "summary"),
                    "tags": _keyword_value(decorator, "tags"),
                }

        self.assertEqual(routes["/adapter/dingtalk/read"]["summary"], "读取钉钉文档")
        self.assertEqual(routes["/workflow/start"]["summary"], "创建交付工作流")
        self.assertEqual(routes["/callbacks/yunxiao/flow-event/public"]["summary"], "接收云效公开流水线事件")
        self.assertEqual(routes["/adapter/execute"]["tags"], ["适配器执行"])

        for route_path, metadata in routes.items():
            if route_path == YUNXIAO_FLOW_EVENT_PUBLIC_PATH:
                route_path = "/callbacks/yunxiao/flow-event/public"
            self.assertTrue(metadata["summary"], route_path)
            self.assertRegex(str(metadata["summary"]), r"[\u4e00-\u9fff]", route_path)
            self.assertTrue(metadata["tags"], route_path)


YUNXIAO_FLOW_EVENT_PUBLIC_PATH = "/callbacks/yunxiao/flow-event/public"


def _is_app_route(decorator: ast.AST) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "app"
        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
    )


def _route_path(decorator: ast.Call) -> str | None:
    if not decorator.args:
        return None
    first_arg = decorator.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    if isinstance(first_arg, ast.Name) and first_arg.id == "YUNXIAO_FLOW_EVENT_PUBLIC_PATH":
        return YUNXIAO_FLOW_EVENT_PUBLIC_PATH
    if isinstance(first_arg, ast.Name) and first_arg.id == "YUNXIAO_FLOW_EVENT_PATH":
        return "/callbacks/yunxiao/flow-event"
    return None


def _keyword_value(decorator: ast.Call, name: str) -> object:
    for keyword in decorator.keywords:
        if keyword.arg == name:
            return ast.literal_eval(keyword.value)
    return None


if __name__ == "__main__":
    unittest.main()
