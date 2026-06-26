from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class YunxiaoWorkflowGuardError(ValueError):
    """云效工作流守卫异常。"""


def load_workflow_json(path: str | Path) -> dict[str, Any]:
    """从文件读取 workflow JSON。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise YunxiaoWorkflowGuardError("Workflow JSON must be an object")
    return data


def assert_yunxiao_create_result_valid(workflow: dict[str, Any], result: dict[str, Any] | None = None) -> None:
    """校验云效需求树创建结果，防止需求/任务/迭代/父子关系写偏。"""
    requirement = _requirement(workflow)
    expected_demands = _demands(requirement)
    if not expected_demands:
        return

    create_result = result if isinstance(result, dict) else _create_result(workflow)
    errors: list[str] = []
    version = _clean(requirement.get("version"))
    actual_demands = _demands(create_result)
    expected_task_count = sum(len(_items(demand)) for demand in expected_demands)
    actual_task_ids = _clean_list(create_result.get("taskIdentifiers") or create_result.get("taskIds"))

    _expect(_clean(create_result.get("category")) == "Req", errors, "root workitem category must be Req")
    _expect(_clean(create_result.get("workitemIdentifier")), errors, "root requirement workitemIdentifier is required")
    _expect(len(actual_demands) == len(expected_demands), errors, "demands detail must contain every parsed demand")
    _expect(_count(create_result.get("demandCount"), len(actual_demands)) == len(expected_demands), errors, "demandCount must match parsed demands")
    _expect(_count(create_result.get("taskCount"), len(actual_task_ids)) == expected_task_count, errors, "taskCount must match parsed tasks")
    if expected_task_count:
        _expect(len(actual_task_ids) == expected_task_count, errors, "taskIdentifiers must contain every created child task")
    if version:
        _expect(_clean(create_result.get("sprintId")), errors, "root requirement sprintId is required when document version exists")

    for demand_index, demand_record in enumerate(actual_demands, start=1):
        demand_id = _clean(demand_record.get("workitemIdentifier"))
        _expect(demand_id, errors, f"demand[{demand_index}] workitemIdentifier is required")
        _expect(_clean(demand_record.get("category")) == "Req", errors, f"demand[{demand_index}] category must be Req")
        if version:
            _expect(_clean(demand_record.get("sprintId")), errors, f"demand[{demand_index}] sprintId is required")
        for item_index, item in enumerate(_items(demand_record), start=1):
            task_id = _clean(item.get("workitemIdentifier"))
            _expect(task_id, errors, f"demand[{demand_index}].task[{item_index}] workitemIdentifier is required")
            _expect(_clean(item.get("category")) == "Task", errors, f"demand[{demand_index}].task[{item_index}] category must be Task")
            _expect(_clean(item.get("parentIdentifier")) == demand_id, errors, f"demand[{demand_index}].task[{item_index}] parentIdentifier must equal parent demand id")
            _expect(not actual_task_ids or task_id in actual_task_ids, errors, f"demand[{demand_index}].task[{item_index}] must be listed in taskIdentifiers")
            if version:
                _expect(_clean(item.get("sprintId")), errors, f"demand[{demand_index}].task[{item_index}] sprintId is required")

    if errors:
        raise YunxiaoWorkflowGuardError("Yunxiao create result guard failed: " + "; ".join(errors))


def assert_yunxiao_close_plan_valid(workflow: dict[str, Any]) -> None:
    """校验关单计划，需求树场景必须只关闭子任务。"""
    create_result = _create_result(workflow)
    if not _looks_like_requirement_tree(create_result):
        return
    task_ids = _clean_list(create_result.get("taskIdentifiers") or create_result.get("taskIds"))
    root_id = _clean(create_result.get("workitemIdentifier") or workflow.get("yunxiaoTaskId"))
    errors: list[str] = []
    _expect(task_ids, errors, "requirement-tree workflow must have child task ids before close")
    if root_id:
        _expect(root_id not in task_ids, errors, "close task list must not include root requirement id")
    if errors:
        raise YunxiaoWorkflowGuardError("Yunxiao close plan guard failed: " + "; ".join(errors))


def validate_workflow(workflow: dict[str, Any], *, mode: str = "all") -> list[str]:
    """执行 workflow 离线校验，返回通过的校验项。"""
    checks: list[str] = []
    if mode in {"all", "create-result"}:
        assert_yunxiao_create_result_valid(workflow)
        checks.append("create-result")
    if mode in {"all", "close-plan"}:
        assert_yunxiao_close_plan_valid(workflow)
        checks.append("close-plan")
    if not checks:
        raise YunxiaoWorkflowGuardError(f"Unsupported guard mode: {mode}")
    return checks


def _requirement(workflow: dict[str, Any]) -> dict[str, Any]:
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    requirement = context.get("requirement") if isinstance(context.get("requirement"), dict) else {}
    return requirement


def _create_result(workflow: dict[str, Any]) -> dict[str, Any]:
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    result = yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {}
    return result


def _looks_like_requirement_tree(create_result: dict[str, Any]) -> bool:
    return bool(create_result.get("demandCount") or _demands(create_result))


def _demands(source: dict[str, Any]) -> list[dict[str, Any]]:
    demands = source.get("demands") if isinstance(source, dict) else None
    return [item for item in demands or [] if isinstance(item, dict)]


def _items(source: dict[str, Any]) -> list[dict[str, Any]]:
    items = source.get("items") if isinstance(source, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_clean(item) for item in value) if item]


def _count(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _expect(condition: Any, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)
