import ast
import unittest
from pathlib import Path


MAIN_FILE = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _load_module() -> ast.Module:
    return ast.parse(MAIN_FILE.read_text(encoding="utf-8"))


def _find_function(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def _find_assignment(module: ast.Module, name: str) -> ast.AST:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return node.value
    raise AssertionError(f"assignment not found: {name}")


def _get_decorator_call(function: ast.FunctionDef) -> ast.Call:
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call):
            return decorator
    raise AssertionError(f"no call decorator found for: {function.name}")


def _assert_requires_api_token(testcase: unittest.TestCase, decorator: ast.Call) -> None:
    testcase.assertEqual(len(decorator.keywords), 1)
    keyword = decorator.keywords[0]
    testcase.assertEqual(keyword.arg, "dependencies")
    testcase.assertIsInstance(keyword.value, ast.List)
    testcase.assertEqual(len(keyword.value.elts), 1)
    depends_call = keyword.value.elts[0]
    testcase.assertIsInstance(depends_call, ast.Call)
    testcase.assertEqual(ast.unparse(depends_call.func), "Depends")
    testcase.assertEqual(len(depends_call.args), 1)
    testcase.assertEqual(ast.unparse(depends_call.args[0]), "require_api_token")


class FlowEventRouteTest(unittest.TestCase):
    def test_private_flow_event_route_still_requires_token(self) -> None:
        module = _load_module()
        self.assertEqual(ast.literal_eval(_find_assignment(module, "YUNXIAO_FLOW_EVENT_PATH")), "/callbacks/yunxiao/flow-event")
        function = _find_function(module, "yunxiao_flow_event")
        decorator = _get_decorator_call(function)
        self.assertEqual(ast.unparse(decorator.func), "app.post")
        self.assertEqual(ast.unparse(decorator.args[0]), "YUNXIAO_FLOW_EVENT_PATH")
        _assert_requires_api_token(self, decorator)

    def test_public_flow_event_route_stays_public(self) -> None:
        module = _load_module()
        self.assertEqual(
            ast.literal_eval(_find_assignment(module, "YUNXIAO_FLOW_EVENT_PUBLIC_PATH")),
            "/callbacks/yunxiao/flow-event/public",
        )
        function = _find_function(module, "yunxiao_flow_event_public")
        decorator = _get_decorator_call(function)
        self.assertEqual(ast.unparse(decorator.func), "app.post")
        self.assertEqual(ast.unparse(decorator.args[0]), "YUNXIAO_FLOW_EVENT_PUBLIC_PATH")
        self.assertFalse(decorator.keywords)

    def test_dingtalk_config_route_requires_token(self) -> None:
        module = _load_module()
        function = _find_function(module, "adapter_dingtalk_config")
        decorator = _get_decorator_call(function)
        self.assertEqual(ast.unparse(decorator.func), "app.post")
        self.assertEqual(ast.literal_eval(decorator.args[0]), "/adapter/dingtalk/config")
        _assert_requires_api_token(self, decorator)

    def test_dingtalk_resolve_operator_route_requires_token(self) -> None:
        module = _load_module()
        function = _find_function(module, "adapter_dingtalk_resolve_operator")
        decorator = _get_decorator_call(function)
        self.assertEqual(ast.unparse(decorator.func), "app.post")
        self.assertEqual(ast.literal_eval(decorator.args[0]), "/adapter/dingtalk/resolve-operator")
        _assert_requires_api_token(self, decorator)


if __name__ == "__main__":
    unittest.main()
