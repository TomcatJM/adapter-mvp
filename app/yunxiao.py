from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from app import db
from app.yunxiao_pipeline import yunxiao_close_task_ids_from_commit_message
from app.yunxiao_guard import (
    YunxiaoWorkflowGuardError,
    assert_yunxiao_close_plan_valid,
    assert_yunxiao_create_result_valid,
)


DEFAULT_ENDPOINT = "devops.cn-hangzhou.aliyuncs.com"
PERSONAL_TOKEN_ENDPOINT = "openapi-rdc.aliyuncs.com"
OPENAPI_VERSION = "2021-06-25"
CREATE_WORKITEM_ACTION = "CreateWorkitemV2"
GET_WORKITEM_ACTION = "GetWorkItemInfo"
CREATE_WORKITEM_COMMENT_ACTION = "CreateWorkitemComment"
UPDATE_WORKITEM_ACTION = "UpdateWorkItem"
DEFAULT_DONE_STATUS_FIELD_ID = "status"
DEFAULT_DONE_STATUS_NAMES = ("已完成", "完成", "已关闭", "done", "closed")
SECRET_RE = re.compile(
    r"(?i)(token|secret|password|passwd|cookie|authorization|access[_-]?key)([=:]\s*)[^\s,;]+"
)
SECRET_KEYWORDS = ("token", "secret", "password", "passwd", "cookie", "authorization", "accesskey", "access_key")


class YunxiaoError(RuntimeError):
    """云效相关异常。"""
    pass


class YunxiaoCloseSkipped(YunxiaoError):
    """云效关单被显式跳过。"""
    pass


class YunxiaoRequirementTreeError(YunxiaoError):
    """云效需求树创建异常。"""
    def __init__(self, message: str, *, partial_result: dict[str, Any] | None = None) -> None:
        """初始化对象。"""
        super().__init__(message)
        self.partial_result = partial_result or {}


def create_yunxiao_workitem(
    workflow: dict[str, Any],
    operator: str | None = None,
    *,
    subject: str | None = None,
    description: str | None = None,
    parent_identifier: str | None = None,
    requested_assignee: str | None = None,
) -> dict[str, Any]:
    """创建云效工作项。"""
    config = _load_config(workflow, purpose="create")
    if _requirement_has_demands(workflow):
        result = _create_yunxiao_requirement_tree(
            workflow,
            config,
            operator,
            subject=subject,
            description=description,
            parent_identifier=parent_identifier,
            requested_assignee=requested_assignee,
        )
        try:
            assert_yunxiao_create_result_valid(workflow, result)
        except YunxiaoWorkflowGuardError as exc:
            raise YunxiaoError(str(exc)) from exc
        return result
    payload = build_create_workitem_payload(
        workflow,
        config,
        operator,
        subject=subject,
        description=description,
        parent_identifier=parent_identifier,
        requested_assignee=requested_assignee,
    )
    response = _request_create_workitem(payload, config)
    _require_api_success(response, "Yunxiao create workitem")
    workitem_id = _extract_workitem_identifier(response)
    if not workitem_id:
        raise YunxiaoError(f"Yunxiao create workitem failed: {_response_error(response)}")
    workitem_display_id = _extract_workitem_display_id(response)
    if not workitem_display_id and config.get("authType") == "personal_token":
        workitem_display_id = _fetch_workitem_display_id_after_create(workitem_id, config)
    return {
        "workitemIdentifier": workitem_id,
        "workitemDisplayId": workitem_display_id,
        "requestId": _pick(response, "requestId", "RequestId"),
        "projectId": config["projectId"],
        "projectName": config.get("projectName"),
        "organizationId": config["organizationId"],
        "category": config["category"],
        "workitemTypeIdentifier": config["workitemTypeIdentifier"],
        "assignee": {
            "name": config.get("assigneeName"),
            "accountId": config.get("assignee"),
            "source": config.get("assigneeSource"),
        },
        "title": payload["subject"],
        "configSource": config.get("configSource"),
        "authType": config.get("authType"),
        "response": _safe_response(response),
    }


def _request_create_workitem(payload: dict[str, Any], config: dict[str, Any]) -> Any:
    """内部辅助函数：请求创建工作项。"""
    if config.get("authType") == "legacy_token":
        return _request_yunxiao_legacy_openapi(payload=payload, config=config, timeout=config["timeout"])
    if config.get("authType") == "personal_token":
        return _request_yunxiao_personal_token_rest(
            method="POST",
            path=_personal_token_workitem_path(config),
            payload=_personal_token_workitem_payload(payload, config),
            config=config,
            timeout=config["timeout"],
        )
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    return _request_yunxiao_openapi(
        method="POST",
        path=f"/organization/{organization_id}/workitem",
        action=CREATE_WORKITEM_ACTION,
        payload=payload,
        config=config,
        timeout=config["timeout"],
    )


def close_yunxiao_workitem(
    workflow: dict[str, Any],
    operator: str | None = None,
    *,
    explicit_refs: list[str] | None = None,
) -> dict[str, Any]:
    """关闭云效工作项。"""
    close_refs = _unique_texts(explicit_refs or _workflow_explicit_close_references(workflow))
    if not close_refs:
        raise YunxiaoCloseSkipped(
            "Yunxiao explicit close task ids missing: add commit message line like "
            "'云效任务: AYRR-4062、 AYRR-4063'. No Yunxiao workitem will be closed."
        )

    try:
        assert_yunxiao_close_plan_valid(workflow)
    except YunxiaoWorkflowGuardError as exc:
        raise YunxiaoError(str(exc)) from exc

    workitem_ids = _workflow_close_workitem_ids(workflow, close_refs)
    if not workitem_ids:
        if not _workflow_has_requirement_tree(workflow) and not _clean_text(workflow.get("yunxiaoTaskId")):
            raise YunxiaoError(
                "Yunxiao task id missing: workflow.yunxiaoTaskId is required before closing. "
                "Solution: create or bind the Yunxiao workitem first."
            )
        raise YunxiaoCloseSkipped(
            "Yunxiao explicit close task ids did not match workflow child tasks: "
            f"explicitTaskIds={', '.join(close_refs)}. No Yunxiao workitem will be closed."
        )

    config = _load_config(workflow, purpose="close")
    if config.get("authType") == "legacy_token":
        raise YunxiaoError(
            "Yunxiao close/writeback requires acs_ak OpenAPI auth. "
            "legacy_token only supports the compatibility create path and cannot close workitems. "
            f"Solution: configure adapter_yunxiao_account_config accountName={config.get('accountName') or ''} "
            "with auth_type=acs_ak, access_key_id, access_key_secret, and endpoint=devops.cn-hangzhou.aliyuncs.com."
        )
    demand_status_snapshots = _snapshot_requirement_demand_statuses(workflow, config)
    closed_results: list[dict[str, Any]] = []
    skipped_results: list[dict[str, Any]] = []
    for workitem_id in workitem_ids:
        current = get_yunxiao_workitem(workitem_id, config)
        current_display_id = _extract_workitem_display_id(current) or workitem_id
        if _is_workitem_closed(current, config):
            skipped_results.append(
                {
                    "workitemIdentifier": workitem_id,
                    "workitemDisplayId": current_display_id,
                    "alreadyClosed": True,
                    "closedStatus": _extract_status_identifier(current),
                    "closedStatusName": _extract_status_name(current),
                }
            )
            continue

        _validate_close_target(config)
        comment = build_close_writeback_content(
            workflow,
            operator,
            workitem_display_id=current_display_id,
            workitem_identifier=workitem_id,
        )
        comment_response = add_yunxiao_workitem_comment(workitem_id, comment, config)
        close_response = update_yunxiao_workitem_done_status(workitem_id, config)
        after = get_yunxiao_workitem(workitem_id, config)
        if _has_extractable_status(after) and not _is_workitem_closed(after, config):
            raise YunxiaoError(
                "Yunxiao workitem close verification failed: "
                f"workitem={workitem_id} currentStatus={_extract_status_identifier(after) or _extract_status_name(after) or 'unknown'} "
                f"expectedDoneStatus={config.get('doneStatusId') or config.get('closeTransitionId')}"
            )
        closed_results.append(
            {
                "workitemIdentifier": workitem_id,
                "workitemDisplayId": _extract_workitem_display_id(after),
                "alreadyClosed": False,
                "closedStatus": _extract_status_identifier(after) or config.get("doneStatusId"),
                "closedStatusName": _extract_status_name(after),
                "comment": _safe_response(comment_response),
                "close": _safe_response(close_response),
            }
        )
    restored_demands = _restore_requirement_demand_statuses(demand_status_snapshots, config)
    all_results = closed_results + skipped_results
    primary_result = all_results[0] if all_results else {"workitemIdentifier": workitem_ids[0], "alreadyClosed": True}
    return {
        "workitemIdentifier": primary_result["workitemIdentifier"],
        "workitemDisplayId": primary_result.get("workitemDisplayId"),
        "alreadyClosed": bool(primary_result.get("alreadyClosed")) and not closed_results,
        "closedStatus": primary_result.get("closedStatus"),
        "closedStatusName": primary_result.get("closedStatusName"),
        "writeback": "skipped" if not closed_results else "success",
        "comment": closed_results[0]["comment"] if closed_results else None,
        "close": closed_results[0]["close"] if closed_results else None,
        "closedTaskIds": [item["workitemIdentifier"] for item in closed_results],
        "skippedTaskIds": [item["workitemIdentifier"] for item in skipped_results],
        "restoredDemandIds": [item["workitemIdentifier"] for item in restored_demands],
        "restoredDemands": restored_demands,
        "results": all_results,
        "configSource": config.get("configSource"),
        "authType": config.get("authType"),
    }


def delete_yunxiao_workitems(
    workflow: dict[str, Any],
    workitem_ids: list[str],
    *,
    operator: str,
    dry_run: bool = True,
    include_demands: bool = False,
) -> dict[str, Any]:
    """删除明确指定的云效工作项。"""
    explicit_ids = _unique_texts(workitem_ids)
    delete_plan = explicit_ids or _workflow_delete_workitem_ids(workflow, include_demands=include_demands)
    if not delete_plan:
        raise YunxiaoError("Yunxiao delete requires explicit workitemIds or a workflow with recorded Yunxiao workitems")

    config = _load_config(workflow, purpose="delete")
    if config.get("authType") != "personal_token":
        raise YunxiaoError("Yunxiao delete requires personal_token auth; configure a scoped Yunxiao personal token account.")

    result: dict[str, Any] = {
        "dryRun": bool(dry_run),
        "operator": operator,
        "projectName": config.get("projectName"),
        "deletePlan": delete_plan,
        "deleted": [],
        "authType": config.get("authType"),
    }
    if dry_run:
        return result

    deleted: list[dict[str, Any]] = []
    for workitem_id in delete_plan:
        response = delete_yunxiao_workitem(workitem_id, config)
        deleted.append(
            {
                "workitemIdentifier": workitem_id,
                "response": _safe_response(response),
            }
        )
    result["deleted"] = deleted
    return result


def delete_yunxiao_workitem(workitem_id: str, config: dict[str, Any]) -> Any:
    """删除单个云效工作项。"""
    workitem_id = _clean_text(workitem_id)
    if not workitem_id:
        raise YunxiaoError("Yunxiao delete workitem id is required")
    if config.get("authType") != "personal_token":
        raise YunxiaoError("Yunxiao delete requires personal_token auth")
    response = _request_yunxiao_personal_token_rest(
        method="DELETE",
        path=_personal_token_workitem_path(config, urllib.parse.quote(workitem_id, safe="")),
        payload=None,
        config=config,
        timeout=config["timeout"],
    )
    _require_api_success(response, "Yunxiao delete workitem")
    return response


def _workflow_delete_workitem_ids(workflow: dict[str, Any], *, include_demands: bool) -> list[str]:
    """从 workflow 创建结果中提取删除顺序：任务在前，需求在后。"""
    ids: list[str] = []
    for record in _workflow_requirement_task_reference_records(workflow):
        workitem_id = _clean_text(record.get("workitemIdentifier"))
        if workitem_id:
            ids.append(workitem_id)
    if include_demands:
        ids.extend(_workflow_requirement_demand_ids(workflow))
    return _unique_texts(ids)


def _snapshot_requirement_demand_statuses(workflow: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """记录需求树父需求状态，避免关闭子任务后被云效联动关需求。"""
    snapshots: list[dict[str, Any]] = []
    if not _workflow_has_requirement_tree(workflow):
        return snapshots
    task_ids = set(_workflow_close_workitem_ids(workflow, _workflow_explicit_close_references(workflow)))
    for demand_id in _workflow_requirement_demand_ids(workflow):
        if demand_id in task_ids:
            continue
        current = get_yunxiao_workitem(demand_id, config)
        snapshots.append(
            {
                "workitemIdentifier": demand_id,
                "workitemDisplayId": _extract_workitem_display_id(current) or demand_id,
                "status": _extract_status_identifier(current),
                "statusName": _extract_status_name(current),
                "alreadyClosed": _is_workitem_closed(current, config),
            }
        )
    return snapshots


def _restore_requirement_demand_statuses(
    snapshots: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """恢复被云效父子联动自动完成的父需求状态。"""
    restored: list[dict[str, Any]] = []
    for snapshot in snapshots:
        original_status = _clean_text(snapshot.get("status"))
        demand_id = _clean_text(snapshot.get("workitemIdentifier"))
        if not demand_id or not original_status or snapshot.get("alreadyClosed"):
            continue
        current = get_yunxiao_workitem(demand_id, config)
        current_status = _extract_status_identifier(current)
        if current_status == original_status or not _is_workitem_closed(current, config):
            continue
        restore_response = update_yunxiao_workitem_status(demand_id, original_status, config)
        after = get_yunxiao_workitem(demand_id, config)
        restored_status = _extract_status_identifier(after)
        if restored_status != original_status:
            raise YunxiaoError(
                "Yunxiao requirement demand restore failed: "
                f"workitem={demand_id} currentStatus={restored_status or _extract_status_name(after) or 'unknown'} "
                f"expectedStatus={original_status}"
            )
        restored.append(
            {
                "workitemIdentifier": demand_id,
                "workitemDisplayId": _extract_workitem_display_id(after) or snapshot.get("workitemDisplayId"),
                "fromStatus": current_status,
                "toStatus": restored_status,
                "toStatusName": _extract_status_name(after),
                "restore": _safe_response(restore_response),
            }
        )
    return restored


def _workflow_close_workitem_ids(workflow: dict[str, Any], explicit_refs: list[str]) -> list[str]:
    """内部辅助函数：工作流关闭工作项ids。"""
    if not explicit_refs:
        return []
    if _workflow_has_requirement_tree(workflow):
        return _match_requirement_tree_task_ids(workflow, explicit_refs)

    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    create_result = yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {}
    workitem_id = _clean_text(workflow.get("yunxiaoTaskId") or create_result.get("workitemIdentifier"))
    refs = _workflow_single_workitem_refs(workflow, create_result)
    explicit = {_normalize_workitem_ref(ref) for ref in explicit_refs}
    if workitem_id and explicit.intersection({_normalize_workitem_ref(ref) for ref in refs}):
        return [workitem_id]
    return []


def _workflow_explicit_close_references(workflow: dict[str, Any]) -> list[str]:
    """从流水线提交信息中提取显式允许关单的云效任务 ID。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    messages = [
        workflow.get("commitMessage"),
        (context.get("pipeline") or {}).get("commitMessage") if isinstance(context.get("pipeline"), dict) else None,
        (context.get("codingResult") or {}).get("commitMessage") if isinstance(context.get("codingResult"), dict) else None,
    ]
    refs: list[str] = []
    for message in messages:
        refs.extend(yunxiao_close_task_ids_from_commit_message(_clean_text(message) or ""))
    return _unique_texts(refs)


def _workflow_single_workitem_refs(workflow: dict[str, Any], create_result: dict[str, Any]) -> list[str]:
    """提取单工作项 workflow 的可匹配 ID。"""
    values = [
        workflow.get("yunxiaoTaskId"),
        workflow.get("yunxiaoTaskDisplayId"),
        create_result.get("workitemIdentifier"),
        create_result.get("workitemDisplayId"),
        create_result.get("serialNumber"),
        create_result.get("serialNo"),
        create_result.get("yunxiaoTaskId"),
        create_result.get("yunxiaoTaskDisplayId"),
    ]
    return _unique_texts(values)


def _match_requirement_tree_task_ids(workflow: dict[str, Any], explicit_refs: list[str]) -> list[str]:
    """把提交信息里的云效展示 ID 映射为需求树里的子任务内部 ID。"""
    task_records = _workflow_requirement_task_reference_records(workflow)
    matched_ids: list[str] = []
    seen: set[str] = set()
    for explicit_ref in explicit_refs:
        normalized_ref = _normalize_workitem_ref(explicit_ref)
        if not normalized_ref:
            continue
        for record in task_records:
            workitem_id = record["workitemIdentifier"]
            refs = {_normalize_workitem_ref(ref) for ref in record["refs"]}
            if normalized_ref not in refs or workitem_id in seen:
                continue
            seen.add(workitem_id)
            matched_ids.append(workitem_id)
            break
    return matched_ids


def _workflow_requirement_task_reference_records(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """提取需求树中任务工作项的内部 ID 和展示 ID。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    create_result = yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {}
    records: dict[str, set[str]] = {}
    demands = create_result.get("demands")
    if isinstance(demands, list):
        for demand in demands:
            if not isinstance(demand, dict):
                continue
            demand_id = _clean_text(demand.get("workitemIdentifier"))
            items = demand.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if _clean_text(item.get("category")) != "Task":
                    continue
                if demand_id and _clean_text(item.get("parentIdentifier")) != demand_id:
                    continue
                workitem_id = _clean_text(item.get("workitemIdentifier"))
                if not workitem_id:
                    continue
                records.setdefault(workitem_id, set()).update(_task_reference_values(item))
    return [
        {"workitemIdentifier": workitem_id, "refs": _unique_texts(list(refs))}
        for workitem_id, refs in records.items()
    ]


def _task_reference_values(item: dict[str, Any]) -> list[str]:
    """提取一个云效任务节点上的所有可见引用。"""
    return _unique_texts(
        [
            item.get("workitemIdentifier"),
            item.get("workitemDisplayId"),
            item.get("serialNumber"),
            item.get("serialNo"),
            item.get("yunxiaoTaskId"),
            item.get("yunxiaoTaskDisplayId"),
        ]
    )


def _normalize_workitem_ref(value: Any) -> str:
    """归一化云效任务引用，便于展示 ID 大小写兼容。"""
    text = _clean_text(value)
    return text.upper() if text else ""


def _unique_texts(values: list[Any]) -> list[str]:
    """保序去重并清理空文本。"""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _workflow_requirement_demand_ids(workflow: dict[str, Any]) -> list[str]:
    """提取需求树父需求 ID。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    create_result = yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {}
    demands = create_result.get("demands")
    if not isinstance(demands, list):
        return []
    ids: list[str] = []
    for demand in demands:
        if not isinstance(demand, dict):
            continue
        demand_id = _clean_text(demand.get("workitemIdentifier"))
        if demand_id:
            ids.append(demand_id)
    return ids


def _workflow_has_requirement_tree(workflow: dict[str, Any]) -> bool:
    """判断 workflow 是否为需求树创建结果。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    create_result = yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {}
    demands = create_result.get("demands")
    return bool(create_result.get("demandCount") or (isinstance(demands, list) and demands))


def get_yunxiao_workitem(workitem_id: str, config: dict[str, Any]) -> Any:
    """获取云效工作项。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    escaped_workitem_id = urllib.parse.quote(workitem_id, safe="")
    path = f"/organization/{organization_id}/workitems/{escaped_workitem_id}"
    if config.get("authType") == "legacy_token":
        response = _request_yunxiao_legacy_rest(
            method="GET",
            path=path,
            payload=None,
            config=config,
            timeout=config["timeout"],
        )
    elif config.get("authType") == "personal_token":
        response = _request_yunxiao_personal_token_rest(
            method="GET",
            path=_personal_token_workitem_path(config, escaped_workitem_id),
            payload=None,
            config=config,
            timeout=config["timeout"],
        )
    else:
        response = _request_yunxiao_openapi(
            method="GET",
            path=path,
            action=GET_WORKITEM_ACTION,
            payload=None,
            config=config,
            timeout=config["timeout"],
        )
    _require_api_success(response, "Yunxiao get workitem")
    return response


def add_yunxiao_workitem_comment(workitem_id: str, content: str, config: dict[str, Any]) -> Any:
    """add云效工作项评论。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    payload = {
        "workitemIdentifier": workitem_id,
        "content": _clip(_sanitize(content), 6000),
        "formatType": config.get("commentFormatType") or "MARKDOWN",
    }
    path = f"/organization/{organization_id}/workitems/comment"
    if config.get("authType") == "legacy_token":
        response = _request_yunxiao_legacy_rest(
            method="POST",
            path=path,
            payload=payload,
            config=config,
            timeout=config["timeout"],
        )
    elif config.get("authType") == "personal_token":
        response = _request_yunxiao_personal_token_rest(
            method="POST",
            path=_personal_token_workitem_path(config, urllib.parse.quote(workitem_id, safe=""), suffix="/comments"),
            payload={"content": payload["content"]},
            config=config,
            timeout=config["timeout"],
        )
    else:
        response = _request_yunxiao_openapi(
            method="POST",
            path=path,
            action=CREATE_WORKITEM_COMMENT_ACTION,
            payload=payload,
            config=config,
            timeout=config["timeout"],
        )
    _require_api_success(response, "Yunxiao create workitem comment")
    return response


def update_yunxiao_workitem_done_status(workitem_id: str, config: dict[str, Any]) -> Any:
    """更新云效工作项done状态。"""
    if config.get("authType") != "personal_token" and config.get("closeTransitionId"):
        organization_id = urllib.parse.quote(config["organizationId"], safe="")
        response = _request_yunxiao_openapi(
            method="PUT",
            path=f"/organization/{organization_id}/workitems/update",
            action=UPDATE_WORKITEM_ACTION,
            payload={
                "identifier": workitem_id,
                "transitionIdentifier": config["closeTransitionId"],
            },
            config=config,
            timeout=config["timeout"],
        )
        _require_api_success(response, "Yunxiao close workitem")
        return response
    done_status_id = config.get("doneStatusId")
    if not done_status_id:
        raise YunxiaoError("Yunxiao close config missing: done_status_id")
    return update_yunxiao_workitem_status(workitem_id, done_status_id, config)


def update_yunxiao_workitem_status(workitem_id: str, status_id: str, config: dict[str, Any]) -> Any:
    """更新云效工作项状态。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    status_id = _clean_text(status_id)
    if not status_id:
        raise YunxiaoError("Yunxiao status id is required")
    if config.get("authType") == "personal_token":
        response = _request_yunxiao_personal_token_rest(
            method="PUT",
            path=_personal_token_workitem_path(config, urllib.parse.quote(workitem_id, safe="")),
            payload={"status": status_id},
            config=config,
            timeout=config["timeout"],
        )
        _require_api_success(response, "Yunxiao update workitem status")
        return response

    field_type = config.get("doneStatusFieldId") or DEFAULT_DONE_STATUS_FIELD_ID
    path = f"/organization/{organization_id}/workitems/update"
    payload = {
        "identifier": workitem_id,
        "propertyKey": field_type,
        "propertyValue": status_id,
        "fieldType": field_type,
    }
    action = UPDATE_WORKITEM_ACTION

    if config.get("authType") == "legacy_token":
        response = _request_yunxiao_legacy_rest(
            method="POST",
            path=path,
            payload=payload,
            config=config,
            timeout=config["timeout"],
        )
    else:
        response = _request_yunxiao_openapi(
            method="POST",
            path=path,
            action=action,
            payload=payload,
            config=config,
        timeout=config["timeout"],
    )
    _require_api_success(response, "Yunxiao update workitem status")
    return response


def build_close_writeback_content(
    workflow: dict[str, Any],
    operator: str | None = None,
    *,
    workitem_display_id: str | None = None,
    workitem_identifier: str | None = None,
) -> str:
    """构建关闭回写content。"""
    context = workflow.get("context") or {}
    coding_result = context.get("codingResult") if isinstance(context.get("codingResult"), dict) else {}
    pipeline = context.get("pipeline") if isinstance(context.get("pipeline"), dict) else {}
    apifox = context.get("apifox") if isinstance(context.get("apifox"), dict) else {}
    apifox_result = apifox.get("lastResult") if isinstance(apifox.get("lastResult"), dict) else apifox
    workitem_display_id = _clean_text(workitem_display_id) or _clean_text(workitem_identifier) or _workflow_workitem_display_id(
        workflow
    )
    lines = [
        "【Adapter 交付回写】",
        f"Workflow：{workflow.get('workflowId') or ''}",
        f"云效工作项：{workitem_display_id or workflow.get('yunxiaoTaskId') or ''}",
        f"流水线：{workflow.get('yunxiaoPipelineId') or pipeline.get('pipelineId') or ''}/{workflow.get('yunxiaoBuildNumber') or pipeline.get('buildNumber') or ''}",
        f"分支：{workflow.get('branchName') or pipeline.get('branchName') or coding_result.get('branchName') or ''}",
        f"提交：{workflow.get('commitId') or pipeline.get('commitId') or coding_result.get('commitId') or ''}",
        f"MR：{coding_result.get('mergeRequestUrl') or ''}",
        f"Apifox：{'已同步' if apifox_result.get('imported') is True or workflow.get('apifoxProjectId') else '未确认'}",
        f"Apifox 项目：{workflow.get('apifoxProjectId') or apifox_result.get('projectId') or ''}",
        "结果：SUCCESS",
        f"操作人：{operator or ''}",
    ]
    return _clip(_sanitize("\n".join(lines)), 6000)


def _workflow_workitem_display_id(workflow: dict[str, Any]) -> str | None:
    """内部辅助函数：工作流工作项展示ID。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    for source in (
        workflow,
        yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {},
        yunxiao.get("closeResult") if isinstance(yunxiao.get("closeResult"), dict) else {},
        context.get("codingRequest") if isinstance(context.get("codingRequest"), dict) else {},
    ):
        value = _clean_text((source or {}).get("yunxiaoTaskDisplayId") or (source or {}).get("workitemDisplayId"))
        if value:
            return value
    return None


def build_create_workitem_payload(
    workflow: dict[str, Any],
    config: dict[str, Any],
    operator: str | None = None,
    *,
    subject: str | None = None,
    description: str | None = None,
    parent_identifier: str | None = None,
    requested_assignee: str | None = None,
) -> dict[str, Any]:
    """构建创建工作项载荷。"""
    requirement = (workflow.get("context") or {}).get("requirement") or {}
    title = (
        _clean_text(subject)
        or _clean_text(requirement.get("summary"))
        or _clean_text(requirement.get("documentTitle"))
        or _clean_text(workflow.get("requirementKey"))
    )
    if not title and isinstance(requirement.get("demands"), list) and requirement["demands"]:
        first_demand = requirement["demands"][0]
        if isinstance(first_demand, dict):
            title = _clean_text(first_demand.get("title")) or _clean_text(workflow.get("requirementKey"))
    if not title:
        raise YunxiaoError("Workflow requirement summary is required before creating Yunxiao workitem")

    assignee = _resolve_workitem_assignee(workflow, config, requested_assignee=requested_assignee)
    if not assignee.get("accountId"):
        raise YunxiaoError(
            "Yunxiao assignee resolution failed: workflow requirement owner or project default assignee is required"
        )

    payload: dict[str, Any] = {
        "subject": _clip(_sanitize(title), 256),
        "description": _clip(_sanitize(description or _build_description(workflow, requirement, operator)), 12000),
        "assignedTo": assignee["accountId"],
        "spaceIdentifier": config["projectId"],
        "category": config["category"],
        "workitemTypeIdentifier": config["workitemTypeIdentifier"],
    }
    if parent_identifier:
        payload["parentIdentifier"] = parent_identifier

    field_values = []
    if config.get("priorityFieldId") and config.get("priorityDefaultValue"):
        field_values.append(
            {
                "fieldIdentifier": config["priorityFieldId"],
                "value": config["priorityDefaultValue"],
            }
        )
    if field_values:
        payload["fieldValueList"] = field_values

    participants = _csv(config.get("participants"))
    if participants:
        payload["participants"] = participants
    trackers = _csv(config.get("trackers"))
    if trackers:
        payload["trackers"] = trackers
    verifier = _clean_text(config.get("verifier"))
    if verifier:
        payload["verifier"] = verifier
    sprint_id = _resolve_workitem_sprint_id(workflow, requirement, config)
    if sprint_id:
        payload["sprint"] = sprint_id
    return payload


def _resolve_workitem_sprint_id(workflow: dict[str, Any], requirement: dict[str, Any], config: dict[str, Any]) -> str | None:
    """解析云效迭代ID：项目配置优先，其次按需求文档版本号精确匹配或创建迭代。"""
    configured_sprint_id = _clean_text(config.get("sprintId"))
    if configured_sprint_id:
        return configured_sprint_id
    version = _clean_text(requirement.get("version"))
    if not version:
        return None
    if config.get("authType") != "personal_token":
        raise YunxiaoError(
            "Yunxiao sprint is unresolved: requirement version is present but sprint_id is not configured. "
            f"version={version} projectName={config.get('projectName') or workflow.get('requirementKey') or ''}"
        )
    sprint = _find_personal_token_sprint_by_version(version, config)
    if not sprint:
        sprint = _create_personal_token_sprint_for_version(workflow, version, config)
    sprint_id = _clean_text(sprint.get("id") or sprint.get("identifier"))
    if not sprint_id:
        raise YunxiaoError(
            "Yunxiao sprint resolved but id is missing: "
            f"version={version} sprintName={_clean_text(sprint.get('name'))}"
        )
    config["sprintId"] = sprint_id
    config["sprintName"] = _clean_text(sprint.get("name"))
    return sprint_id


def _find_personal_token_sprint_by_version(version: str, config: dict[str, Any]) -> dict[str, Any] | None:
    """按需求版本号从云效迭代列表中精确选择迭代，禁止包含式猜测。"""
    candidates = _list_personal_token_sprints(config, name=version)
    matched = _select_sprint_candidate(version, candidates)
    if matched:
        return matched
    candidates = _list_personal_token_sprints(config, name=None)
    return _select_sprint_candidate(version, candidates)


def _create_personal_token_sprint_for_version(
    workflow: dict[str, Any],
    version: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """按文档版本号创建云效迭代。"""
    sprint_name = _clean_text(version)
    if not sprint_name:
        raise YunxiaoError("Yunxiao sprint name is required")
    owner = _resolve_workitem_assignee(workflow, config)
    owner_id = _clean_text(owner.get("accountId"))
    if not owner_id:
        raise YunxiaoError(
            "Yunxiao sprint owner is missing: "
            f"version={sprint_name} projectName={config.get('projectName') or ''}. "
            "Configure adapter_yunxiao_project_member_relation default assignee or project default assignee."
        )
    created = _create_personal_token_sprint(sprint_name, [owner_id], config)
    sprint_id = _clean_text(created.get("id") or created.get("identifier"))
    if sprint_id:
        created.setdefault("name", sprint_name)
        return created

    # Some Yunxiao responses may omit the created id; re-read by exact name before failing.
    matched = _find_personal_token_sprint_by_version(sprint_name, config)
    if matched:
        return matched
    raise YunxiaoError(
        "Yunxiao sprint created but id is missing and exact re-query failed: "
        f"version={sprint_name} projectName={config.get('projectName') or ''}"
    )


def _create_personal_token_sprint(name: str, owner_ids: list[str], config: dict[str, Any]) -> dict[str, Any]:
    """调用云效 personal token API 创建迭代。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    project_id = urllib.parse.quote(config["projectId"], safe="")
    path = f"/oapi/v1/projex/organizations/{organization_id}/projects/{project_id}/sprints"
    payload = {
        "capacityHours": 1,
        "description": "",
        "endDate": "",
        "name": name,
        "owners": owner_ids,
        "startDate": "",
    }
    response = _request_yunxiao_personal_token_rest(
        method="POST",
        path=path,
        payload=payload,
        config=config,
        timeout=config["timeout"],
    )
    _require_api_success(response, "Yunxiao create sprint")
    return _extract_sprint_object(response)


def _list_personal_token_sprints(config: dict[str, Any], *, name: str | None) -> list[dict[str, Any]]:
    """查询云效迭代列表。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    project_id = urllib.parse.quote(config["projectId"], safe="")
    query = {
        "status": "TODO,DOING,ARCHIVED",
        "page": "1",
        "perPage": "100",
    }
    if _clean_text(name):
        query["name"] = _clean_text(name)
    path = (
        f"/oapi/v1/projex/organizations/{organization_id}/projects/{project_id}/sprints?"
        + urllib.parse.urlencode(query)
    )
    response = _request_yunxiao_personal_token_rest(
        method="GET",
        path=path,
        payload=None,
        config=config,
        timeout=config["timeout"],
    )
    return _extract_sprint_list(response)


def _extract_sprint_list(response: Any) -> list[dict[str, Any]]:
    """从云效迭代响应中提取列表。"""
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if not isinstance(response, dict):
        return []
    for source in _dict_candidates(response):
        for key in ("sprints", "items", "list", "data", "result"):
            value = source.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _extract_sprint_list(value)
                if nested:
                    return nested
    return []


def _extract_sprint_object(response: Any) -> dict[str, Any]:
    """从云效迭代创建响应中提取迭代对象。"""
    if not isinstance(response, dict):
        return {}
    for source in _dict_candidates(response):
        if _clean_text(source.get("id") or source.get("identifier")):
            return source
    return response


def _select_sprint_candidate(version: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """选择与版本号精确匹配的迭代，禁止把前后缀相似名称当作命中。"""
    version_norm = _normalize_sprint_match_text(version)
    if not version_norm:
        return None
    matched = [
        candidate for candidate in candidates if _normalize_sprint_match_text(candidate.get("name")) == version_norm
    ]
    if not matched:
        return None
    active = [item for item in matched if _normalize_sprint_status(item.get("status")) in {"TODO", "DOING"}]
    if len(active) == 1:
        return active[0]
    if len(matched) == 1:
        return matched[0]
    names = ", ".join(_clean_text(item.get("name")) for item in matched[:5])
    raise YunxiaoError(f"Yunxiao sprint match is ambiguous: version={version} candidates={names}")


def _normalize_sprint_match_text(value: Any) -> str:
    """归一化迭代名称匹配文本。"""
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _normalize_sprint_status(value: Any) -> str:
    """归一化迭代状态。"""
    return str(value or "").strip().upper()


def _request_yunxiao_openapi(
    *,
    method: str,
    path: str,
    action: str,
    payload: dict[str, Any] | None,
    config: dict[str, Any],
    timeout: int,
) -> Any:
    """内部辅助函数：请求云效OpenAPI。"""
    body = b""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    content_hash = hashlib.sha256(body).hexdigest()
    headers = _signed_headers(config, action, content_hash)
    authorization = _authorization_header(
        method=method.upper(),
        path=path,
        query="",
        headers=headers,
        content_hash=content_hash,
        access_key_id=config["accessKeyId"],
        access_key_secret=config["accessKeySecret"],
    )
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": authorization,
        **{_http_header_name(key): value for key, value in headers.items()},
    }
    url = f"{config['scheme']}://{config['endpoint']}{path}"
    request = urllib.request.Request(url, data=body, method=method.upper(), headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return _parse_json(text)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise YunxiaoError(f"Yunxiao API failed: status={exc.code} {_parse_error_detail(body_text)}") from exc
    except urllib.error.URLError as exc:
        raise YunxiaoError(f"Yunxiao API network error: {_sanitize(str(exc))[:1000]}") from exc


def _request_yunxiao_legacy_openapi(
    *,
    payload: dict[str, Any],
    config: dict[str, Any],
    timeout: int,
) -> Any:
    """内部辅助函数：请求云效兼容OpenAPI。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    url = f"{config['scheme']}://{config['endpoint']}/oapi/v1/projex/organizations/{organization_id}/workitems"
    body = _legacy_workitem_payload(payload, config)
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "x-yunxiao-token": config["legacyToken"],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return _parse_json(text)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise YunxiaoError(f"Yunxiao legacy API failed: status={exc.code} {_parse_error_detail(body_text)}") from exc
    except urllib.error.URLError as exc:
        raise YunxiaoError(f"Yunxiao legacy API network error: {_sanitize(str(exc))[:1000]}") from exc


def _request_yunxiao_legacy_rest(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    config: dict[str, Any],
    timeout: int,
) -> Any:
    """内部辅助函数：请求云效兼容rest。"""
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = config["legacyToken"]
    request = urllib.request.Request(
        f"{config['scheme']}://{config['endpoint']}{path}",
        data=body,
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
            "x-yunxiao-token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return _parse_json(text)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise YunxiaoError(f"Yunxiao legacy API failed: status={exc.code} {_parse_error_detail(body_text)}") from exc
    except urllib.error.URLError as exc:
        raise YunxiaoError(f"Yunxiao legacy API network error: {_sanitize(str(exc))[:1000]}") from exc


def _request_yunxiao_personal_token_rest(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    config: dict[str, Any],
    timeout: int,
) -> Any:
    """内部辅助函数：请求云效personal令牌rest。"""
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{config['scheme']}://{config['endpoint']}{path}",
        data=body,
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "x-yunxiao-token": config["personalToken"],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return _parse_json(text)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise YunxiaoError(f"Yunxiao personal token API failed: status={exc.code} {_parse_error_detail(body_text)}") from exc
    except urllib.error.URLError as exc:
        raise YunxiaoError(f"Yunxiao personal token API network error: {_sanitize(str(exc))[:1000]}") from exc


def _legacy_workitem_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：兼容工作项载荷。"""
    legacy_payload = {
        "organizationId": config["organizationId"],
        "spaceId": config["projectId"],
        "workitemTypeId": config["workitemTypeIdentifier"],
        "subject": payload["subject"],
        "description": payload["description"],
        "assignedTo": payload["assignedTo"],
        "source": {"adapter": "adapter-mvp"},
    }
    if payload.get("sprint"):
        legacy_payload["sprint"] = payload["sprint"]
    return legacy_payload


def _personal_token_workitem_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：personal令牌工作项载荷。"""
    personal_payload: dict[str, Any] = {
        "spaceId": config["projectId"],
        "category": config["category"],
        "workitemTypeId": config["workitemTypeIdentifier"],
        "subject": payload["subject"],
        "description": payload["description"],
        "assignedTo": payload["assignedTo"],
        "capacityHours": 1,
    }
    if payload.get("fieldValueList"):
        personal_payload["fieldValueList"] = payload["fieldValueList"]
    if payload.get("parentIdentifier"):
        personal_payload["parentId"] = payload["parentIdentifier"]
    for key in ("participants", "trackers", "verifier", "sprint"):
        if payload.get(key):
            personal_payload[key] = payload[key]
    return personal_payload


def _personal_token_workitem_path(config: dict[str, Any], workitem_id: str | None = None, suffix: str = "") -> str:
    """内部辅助函数：personal令牌工作项path。"""
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    path = f"/oapi/v1/projex/organizations/{organization_id}/workitems"
    if workitem_id:
        path += f"/{workitem_id}"
    if suffix:
        path += suffix
    return path


def _load_config(workflow: dict[str, Any], *, purpose: str = "create") -> dict[str, Any]:
    """内部辅助函数：加载配置。"""
    project_name = _resolve_project_name(workflow)
    db_config = _load_db_config(project_name, workflow, purpose=purpose)
    if db_config:
        return db_config
    return _load_env_config(project_name, purpose=purpose)


def _load_db_config(project_name: str | None, workflow: dict[str, Any], *, purpose: str) -> dict[str, Any] | None:
    """内部辅助函数：加载数据库配置。"""
    if not db.configured():
        return None
    if not project_name:
        raise YunxiaoError(
            "Yunxiao project name is unresolved. "
            "Set workflow context.projectName, requirement.affectedRepos, repoUrl, or YUNXIAO_DEFAULT_PROJECT_NAME."
        )

    project_config = db.find_yunxiao_project_config(project_name)
    if not project_config:
        raise YunxiaoError(
            "Yunxiao project config missing: "
            f"projectName={project_name}. Configure adapter_yunxiao_project_config."
        )

    account_name = _clean_text(project_config.get("accountName"))
    if not account_name:
        raise YunxiaoError(
            "Yunxiao project config is invalid: "
            f"projectName={project_name} account_name is required"
        )
    account_config = db.find_yunxiao_account_config(account_name)
    if not account_config:
        raise YunxiaoError(
            "Yunxiao account config missing: "
            f"accountName={account_name}. Configure adapter_yunxiao_account_config."
        )

    auth_type = _normalize_auth_type(account_config.get("authType"))
    scheme, endpoint = _normalize_endpoint(account_config.get("endpoint") or _default_endpoint(auth_type))
    assignee = {"name": None, "accountId": project_config.get("assignee"), "source": "not_required"}
    if purpose == "create":
        assignee = _resolve_db_assignee(
            {
                **project_config,
                "workflowContext": workflow.get("context") or {},
            },
            workflow_project_name=project_name,
        )
    config = {
        "configSource": "db",
        "authType": auth_type,
        "projectName": project_config.get("projectName") or project_name,
        "accountName": account_config.get("accountName") or account_name,
        "scheme": scheme,
        "endpoint": endpoint,
        "accessKeyId": account_config.get("accessKeyId"),
        "accessKeySecret": account_config.get("accessKeySecret"),
        "legacyToken": account_config.get("legacyToken"),
        "personalToken": account_config.get("legacyToken"),
        "securityToken": account_config.get("securityToken"),
        "organizationId": project_config.get("organizationId"),
        "projectId": project_config.get("projectId"),
        "sprintId": project_config.get("sprintId"),
        "category": project_config.get("category") or "Req",
        "workitemTypeIdentifier": project_config.get("workitemTypeIdentifier"),
        "requirementCategory": project_config.get("category") or "Req",
        "requirementWorkitemTypeIdentifier": project_config.get("workitemTypeIdentifier"),
        "taskCategory": project_config.get("taskCategory") or "Task",
        "taskWorkitemTypeIdentifier": project_config.get("taskWorkitemTypeIdentifier"),
        "assignee": assignee.get("accountId"),
        "assigneeName": assignee.get("name"),
        "assigneeSource": assignee.get("source"),
        "priorityFieldId": project_config.get("priorityFieldId"),
        "priorityDefaultValue": project_config.get("priorityDefaultValue"),
        "participants": project_config.get("participants"),
        "trackers": project_config.get("trackers"),
        "verifier": project_config.get("verifier"),
        "doneStatusId": project_config.get("doneStatusId"),
        "doneStatusFieldId": project_config.get("doneStatusFieldId") or DEFAULT_DONE_STATUS_FIELD_ID,
        "doneStatusNames": project_config.get("doneStatusNames"),
        "commentFieldKey": project_config.get("commentFieldKey"),
        "commentFormatType": project_config.get("commentFormatType") or "MARKDOWN",
        "closeTransitionId": project_config.get("closeTransitionId"),
        "timeout": _parse_timeout(_first_env("YUNXIAO_OPENAPI_TIMEOUT") or "30"),
    }
    _validate_config(config, _db_required(config, purpose))
    config["timeout"] = max(5, min(int(config["timeout"] or 30), 180))
    return config


def _load_env_config(project_name: str | None, *, purpose: str) -> dict[str, Any]:
    """内部辅助函数：加载env配置。"""
    scheme, endpoint = _normalize_endpoint(
        _first_env("YUNXIAO_OPENAPI_ENDPOINT", "YUNXIAO_OPENAPI_BASE_URL") or DEFAULT_ENDPOINT
    )
    config = {
        "configSource": "env",
        "authType": "acs_ak",
        "projectName": project_name,
        "scheme": scheme,
        "endpoint": endpoint,
        "accessKeyId": _first_env("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_ID"),
        "accessKeySecret": _first_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "ALIYUN_ACCESS_KEY_SECRET"),
        "securityToken": _first_env("ALIBABA_CLOUD_SECURITY_TOKEN", "ALIYUN_SECURITY_TOKEN"),
        "organizationId": _first_env("YUNXIAO_ORGANIZATION_ID", "YUNXIAO_ORG_ID"),
        "projectId": _first_env("YUNXIAO_PROJECT_ID", "YUNXIAO_SPACE_IDENTIFIER"),
        "category": _first_env("YUNXIAO_WORKITEM_CATEGORY") or "Req",
        "workitemTypeIdentifier": _first_env(
            "YUNXIAO_WORKITEM_TYPE_IDENTIFIER",
            "YUNXIAO_WORKITEM_TYPE_ID",
        ),
        "requirementCategory": _first_env("YUNXIAO_WORKITEM_CATEGORY") or "Req",
        "requirementWorkitemTypeIdentifier": _first_env(
            "YUNXIAO_WORKITEM_TYPE_IDENTIFIER",
            "YUNXIAO_WORKITEM_TYPE_ID",
        ),
        "taskCategory": _first_env("YUNXIAO_TASK_WORKITEM_CATEGORY") or "Task",
        "taskWorkitemTypeIdentifier": _first_env(
            "YUNXIAO_TASK_WORKITEM_TYPE_IDENTIFIER",
            "YUNXIAO_TASK_WORKITEM_TYPE_ID",
        ),
        "assignee": _first_env("YUNXIAO_WORKITEM_ASSIGNEE", "YUNXIAO_ASSIGNED_TO"),
        "assigneeName": _first_env("YUNXIAO_WORKITEM_ASSIGNEE_NAME"),
        "assigneeSource": "env",
        "priorityFieldId": _first_env("YUNXIAO_PRIORITY_FIELD_ID"),
        "priorityDefaultValue": _first_env("YUNXIAO_PRIORITY_DEFAULT_VALUE"),
        "participants": _first_env("YUNXIAO_WORKITEM_PARTICIPANTS"),
        "trackers": _first_env("YUNXIAO_WORKITEM_TRACKERS"),
        "verifier": _first_env("YUNXIAO_WORKITEM_VERIFIER"),
        "doneStatusId": _first_env("YUNXIAO_DONE_STATUS_ID", "YUNXIAO_DONE_STATUS_VALUE"),
        "doneStatusFieldId": _first_env("YUNXIAO_DONE_STATUS_FIELD_ID") or DEFAULT_DONE_STATUS_FIELD_ID,
        "doneStatusNames": _first_env("YUNXIAO_DONE_STATUS_NAMES"),
        "commentFieldKey": _first_env("YUNXIAO_COMMENT_FIELD_KEY", "YUNXIAO_WRITEBACK_FIELD"),
        "commentFormatType": _first_env("YUNXIAO_COMMENT_FORMAT_TYPE") or "MARKDOWN",
        "closeTransitionId": _first_env("YUNXIAO_CLOSE_TRANSITION_ID"),
        "timeout": _parse_timeout(_first_env("YUNXIAO_OPENAPI_TIMEOUT") or "30"),
    }
    required = _env_required(config, purpose)
    _validate_config(config, required)
    config["timeout"] = max(5, min(int(config["timeout"] or 30), 180))
    return config


def _validate_config(config: dict[str, Any], required: dict[str, Any]) -> None:
    """内部辅助函数：校验配置。"""
    missing = [name for name, value in required.items() if not value]
    if missing:
        hint = "Yunxiao OpenAPI uses Alibaba Cloud AK auth; YUNXIAO_TOKEN is not enough for this path"
        if config.get("authType") == "legacy_token":
            hint = "Yunxiao legacy token auth is enabled for this account; configure legacy_token or switch auth_type to acs_ak"
        elif config.get("authType") == "personal_token":
            hint = "Yunxiao personal token auth is enabled; configure legacy_token with a Yunxiao personal access token"
        raise YunxiaoError(f"Yunxiao config missing: {', '.join(missing)}. {hint}")


def _db_required(config: dict[str, Any], purpose: str) -> dict[str, Any]:
    """内部辅助函数：数据库required。"""
    required = {
        "adapter_yunxiao_project_config.organization_id": config["organizationId"],
        "adapter_yunxiao_project_config.project_id": config["projectId"],
    }
    if purpose == "create":
        required["adapter_yunxiao_project_config.workitem_type_identifier"] = config["workitemTypeIdentifier"]
        required["adapter_yunxiao_project_member_relation.default_account_id"] = config["assignee"]
    if config.get("authType") == "legacy_token":
        required["adapter_yunxiao_account_config.legacy_token"] = config["legacyToken"]
    elif config.get("authType") == "personal_token":
        required["adapter_yunxiao_account_config.legacy_token"] = config["personalToken"]
    else:
        required["adapter_yunxiao_account_config.access_key_id"] = config["accessKeyId"]
        required["adapter_yunxiao_account_config.access_key_secret"] = config["accessKeySecret"]
    return required


def _env_required(config: dict[str, Any], purpose: str) -> dict[str, Any]:
    """内部辅助函数：envrequired。"""
    required = {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": config["accessKeyId"],
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": config["accessKeySecret"],
        "YUNXIAO_ORGANIZATION_ID": config["organizationId"],
        "YUNXIAO_PROJECT_ID": config["projectId"],
    }
    if purpose == "create":
        required["YUNXIAO_WORKITEM_TYPE_IDENTIFIER"] = config["workitemTypeIdentifier"]
        required["YUNXIAO_WORKITEM_ASSIGNEE"] = config["assignee"]
    return required


def _config_for_workitem_kind(config: dict[str, Any], kind: str) -> dict[str, Any]:
    """按云效工作项类型返回创建配置。"""
    if kind == "task":
        return {
            **config,
            "category": _clean_text(config.get("taskCategory")) or "Task",
            "workitemTypeIdentifier": _clean_text(config.get("taskWorkitemTypeIdentifier")),
        }
    return {
        **config,
        "category": _clean_text(config.get("requirementCategory")) or _clean_text(config.get("category")) or "Req",
        "workitemTypeIdentifier": _clean_text(
            config.get("requirementWorkitemTypeIdentifier") or config.get("workitemTypeIdentifier")
        ),
    }


def _require_task_workitem_config(config: dict[str, Any]) -> None:
    """确保结构化任务不会被错误创建成需求类型。"""
    if _clean_text(config.get("taskWorkitemTypeIdentifier")):
        return
    source = "adapter_yunxiao_project_config.task_workitem_type_identifier"
    if config.get("configSource") == "env":
        source = "YUNXIAO_TASK_WORKITEM_TYPE_IDENTIFIER"
    raise YunxiaoError(
        "Yunxiao task workitem type is missing: "
        f"configure {source}. Requirements and tasks are different Yunxiao workitem types."
    )


def _validate_close_target(config: dict[str, Any]) -> None:
    """内部辅助函数：校验关闭目标。"""
    if config.get("doneStatusId") or config.get("closeTransitionId"):
        return
    raise YunxiaoError(
        "Yunxiao close config missing: done_status_id or close_transition_id. "
        "Solution: configure adapter_yunxiao_project_config.done_status_id "
        "or YUNXIAO_DONE_STATUS_ID after confirming the target done status in Yunxiao."
    )


def _resolve_project_name(workflow: dict[str, Any]) -> str | None:
    """内部辅助函数：解析项目name。"""
    context = workflow.get("context") or {}
    requirement = context.get("requirement") or {}
    for source in (context, requirement):
        for key in ("projectName", "project_name", "serviceName", "service_name", "appName", "app_name"):
            value = _clean_text(source.get(key))
            if value:
                return value

    affected_repo = _first_item(requirement.get("affectedRepos"))
    if affected_repo:
        return affected_repo

    repo_name = _repo_name(workflow.get("repoUrl") or requirement.get("repoUrl"))
    if repo_name:
        return repo_name

    return _first_env("YUNXIAO_DEFAULT_PROJECT_NAME", "YUNXIAO_PROJECT_NAME")


def _resolve_db_assignee(project_config: dict[str, Any], workflow_project_name: str | None) -> dict[str, Any]:
    """内部辅助函数：解析数据库负责人。"""
    project_name = _clean_text(project_config.get("projectName")) or _clean_text(workflow_project_name)
    requested = _resolve_requested_assignee(project_config)
    if requested:
        if not project_name:
            raise YunxiaoError("Yunxiao assignee is specified but projectName is unresolved")
        member = db.find_yunxiao_project_member(project_name, requested)
        if not member:
            raise YunxiaoError(
                "Yunxiao assignee config missing: "
                f"projectName={project_name}, assignee={requested}. "
                "Configure adapter_yunxiao_member and adapter_yunxiao_project_member_relation "
                "with member_name or yunxiao_account_id."
            )
        return {
            "name": member.get("name"),
            "accountId": member.get("accountId"),
            "source": "project_member_requested",
        }

    member = db.find_default_yunxiao_project_member(project_name) if project_name else None
    if member:
        return {
            "name": member.get("name"),
            "accountId": member.get("accountId"),
            "source": "project_member_default",
        }

    fallback = _clean_text(project_config.get("assignee"))
    if fallback:
        return {
            "name": None,
            "accountId": fallback,
            "source": "project_config_default_assignee",
        }
    return {"name": None, "accountId": None, "source": None}


def _resolve_requested_assignee(project_config: dict[str, Any]) -> str | None:
    """内部辅助函数：解析requested负责人。"""
    context = project_config.get("workflowContext")
    if not isinstance(context, dict):
        return None
    requirement = context.get("requirement") if isinstance(context.get("requirement"), dict) else {}
    for source in (requirement, context):
        value = _first_present(
            source,
            "assigneeId",
            "assignee_id",
            "assigneeAccountId",
            "assignee_account_id",
            "ownerId",
            "owner_id",
            "assigneeName",
            "assignee_name",
            "ownerName",
            "owner_name",
            "负责人",
        )
        if value:
            return value
    return None


def _resolve_workitem_assignee(
    workflow: dict[str, Any],
    config: dict[str, Any],
    *,
    requested_assignee: str | None = None,
) -> dict[str, Any]:
    """内部辅助函数：解析工作项负责人。"""
    project_name = _resolve_project_name(workflow) or _clean_text(config.get("projectName"))
    if requested_assignee:
        requested = _clean_text(requested_assignee)
        if requested and project_name:
            member = db.find_yunxiao_project_member(project_name, requested)
            if member:
                return {
                    "name": member.get("name"),
                    "accountId": member.get("accountId"),
                    "source": "project_member_requested",
                }
        if requested:
            raise YunxiaoError(
                "Yunxiao assignee config missing: "
                f"projectName={project_name or ''}, assignee={requested}. "
                "Configure adapter_yunxiao_member and adapter_yunxiao_project_member_relation "
                "with member_name or yunxiao_account_id."
            )

    if config.get("assigneeSource") == "project_member_requested":
        fallback = _clean_text(config.get("assignee"))
        if fallback:
            return {
                "name": _clean_text(config.get("assigneeName")),
                "accountId": fallback,
                "source": "project_member_requested",
            }
    if project_name:
        member = db.find_default_yunxiao_project_member(project_name)
        if member:
            return {
                "name": member.get("name"),
                "accountId": member.get("accountId"),
                "source": "project_member_default",
            }

    fallback = _clean_text(config.get("assignee"))
    if fallback:
        return {
            "name": _clean_text(config.get("assigneeName")),
            "accountId": fallback,
            "source": config.get("assigneeSource") or "project_config_default_assignee",
        }
    if requested_assignee:
        requested = _clean_text(requested_assignee)
        if requested:
            raise YunxiaoError(
                "Yunxiao assignee config missing: "
                f"projectName={project_name or ''}, assignee={requested}. "
                "Configure adapter_yunxiao_member and adapter_yunxiao_project_member_relation "
                "with member_name or yunxiao_account_id, or set a project default assignee."
            )
    return {"name": None, "accountId": None, "source": None}


def _normalize_auth_type(value: Any) -> str:
    """内部辅助函数：归一化鉴权类型。"""
    normalized = str(value or "acs_ak").strip().lower()
    if normalized in {"legacy", "token", "yunxiao_token"}:
        return "legacy_token"
    if normalized in {"personal", "personal_access_token", "pat"}:
        return "personal_token"
    if normalized not in {"acs_ak", "legacy_token", "personal_token"}:
        raise YunxiaoError(f"Unsupported Yunxiao auth_type: {normalized}")
    return normalized


def _default_endpoint(auth_type: str) -> str:
    """内部辅助函数：defaultendpoint。"""
    if auth_type == "personal_token":
        return PERSONAL_TOKEN_ENDPOINT
    return DEFAULT_ENDPOINT


def _signed_headers(config: dict[str, Any], action: str, content_hash: str) -> dict[str, str]:
    """内部辅助函数：signedheaders。"""
    headers = {
        "host": config["endpoint"],
        "x-acs-action": action,
        "x-acs-version": OPENAPI_VERSION,
        "x-acs-date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x-acs-signature-nonce": uuid.uuid4().hex,
        "x-acs-content-sha256": content_hash,
    }
    if config.get("securityToken"):
        headers["x-acs-security-token"] = config["securityToken"]
    return headers


def _authorization_header(
    *,
    method: str,
    path: str,
    query: str,
    headers: dict[str, str],
    content_hash: str,
    access_key_id: str,
    access_key_secret: str,
) -> str:
    """内部辅助函数：authorizationheader。"""
    signed_header_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{_normalize_header_value(headers[name])}\n" for name in signed_header_names)
    signed_headers = ";".join(signed_header_names)
    canonical_request = "\n".join(
        [
            method,
            path or "/",
            query,
            canonical_headers,
            signed_headers,
            content_hash,
        ]
    )
    hashed_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"ACS3-HMAC-SHA256\n{hashed_request}"
    signature = hmac.new(
        access_key_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"ACS3-HMAC-SHA256 Credential={access_key_id},SignedHeaders={signed_headers},Signature={signature}"


def _build_description(workflow: dict[str, Any], requirement: dict[str, Any], operator: str | None) -> str:
    """内部辅助函数：构建描述。"""
    lines = [
        "来源：钉钉需求文档",
        f"Workflow：{workflow.get('workflowId') or ''}",
        f"钉钉链接：{workflow.get('dingtalkUrl') or ''}",
        f"需求键：{workflow.get('requirementKey') or ''}",
        f"仓库：{workflow.get('repoUrl') or _join(requirement.get('affectedRepos'))}",
        f"计划分支：{workflow.get('branchName') or ''}",
        f"操作人：{operator or ''}",
        "",
        "需求摘要：",
        str(requirement.get("summary") or ""),
        "",
        "结构化需求：",
        _format_requirement_demands(requirement.get("demands")),
        "",
        "验收标准：",
        _format_list(requirement.get("acceptanceCriteria")),
        "",
        "接口变更：",
        _format_api_changes(requirement.get("apiChanges")),
        "",
        "测试范围：",
        _format_list(requirement.get("testScope")),
        "",
        f"风险：{requirement.get('risk') or '未提供'}",
        "",
        "未决问题：",
        _format_list(requirement.get("openQuestions")),
    ]
    return _clip(_sanitize("\n".join(lines)), 12000)


def _requirement_has_demands(workflow: dict[str, Any]) -> bool:
    """内部辅助函数：requirementhasdemands。"""
    requirement = (workflow.get("context") or {}).get("requirement") or {}
    demands = requirement.get("demands")
    return isinstance(demands, list) and any(isinstance(demand, dict) for demand in demands)


def _create_yunxiao_requirement_tree(
    workflow: dict[str, Any],
    config: dict[str, Any],
    operator: str | None = None,
    *,
    subject: str | None = None,
    description: str | None = None,
    parent_identifier: str | None = None,
    requested_assignee: str | None = None,
) -> dict[str, Any]:
    """内部辅助函数：创建云效requirement树。"""
    requirement = (workflow.get("context") or {}).get("requirement") or {}
    demands = [demand for demand in requirement.get("demands") or [] if isinstance(demand, dict)]
    if not demands:
        payload = build_create_workitem_payload(
            workflow,
            config,
            operator,
            subject=subject,
            description=description,
            parent_identifier=parent_identifier,
            requested_assignee=requested_assignee,
        )
        response = _request_create_workitem(payload, config)
        _require_api_success(response, "Yunxiao create workitem")
        workitem_id = _extract_workitem_identifier(response)
        if not workitem_id:
            raise YunxiaoError(f"Yunxiao create workitem failed: {_response_error(response)}")
        workitem_display_id = _extract_workitem_display_id(response)
        if not workitem_display_id and config.get("authType") == "personal_token":
            workitem_display_id = _fetch_workitem_display_id_after_create(workitem_id, config)
        return {
            "workitemIdentifier": workitem_id,
            "workitemDisplayId": workitem_display_id,
            "requestId": _pick(response, "requestId", "RequestId"),
            "projectId": config["projectId"],
            "projectName": config.get("projectName"),
            "organizationId": config["organizationId"],
            "category": config["category"],
            "workitemTypeIdentifier": config["workitemTypeIdentifier"],
            "assignee": {
                "name": config.get("assigneeName"),
                "accountId": config.get("assignee"),
                "source": config.get("assigneeSource"),
            },
            "title": payload["subject"],
            "description": payload["description"],
            "parentIdentifier": payload.get("parentIdentifier"),
            "sprintId": payload.get("sprint"),
            "configSource": config.get("configSource"),
            "authType": config.get("authType"),
            "response": _safe_response(response),
        }

    created_demands: list[dict[str, Any]] = []
    created_task_ids: list[str] = []
    primary_demand: dict[str, Any] | None = None
    demand_config = _config_for_workitem_kind(config, "requirement")
    task_config = _config_for_workitem_kind(config, "task")
    if any((demand.get("items") or []) for demand in demands if isinstance(demand, dict)):
        _require_task_workitem_config(config)
    try:
        _validate_requirement_tree_task_owners(workflow, config, demands)
        for demand in demands:
            demand_title = _clean_text(demand.get("title"))
            if not demand_title:
                raise YunxiaoError(
                    "Requirement demand title is required before creating Yunxiao workitems. "
                    "Do not infer it from documentTitle, requirementKey, or another demand."
                )
            demand_description = _build_requirement_demand_description(workflow, requirement, demand, operator)
            demand_result = _create_yunxiao_single_workitem(
                workflow,
                demand_config,
                operator,
                subject=demand_title,
                description=demand_description,
            )
            if primary_demand is None:
                primary_demand = demand_result
            demand_items: list[dict[str, Any]] = []
            demand_record = {
                "demandIndex": demand.get("demandIndex"),
                "title": demand_title,
                "description": _clean_text(demand.get("description")),
                "workitemIdentifier": demand_result["workitemIdentifier"],
                "workitemDisplayId": demand_result.get("workitemDisplayId"),
                "category": demand_result.get("category"),
                "workitemTypeIdentifier": demand_result.get("workitemTypeIdentifier"),
                "sprintId": demand_result.get("sprintId"),
                "items": demand_items,
            }
            created_demands.append(demand_record)
            for item in demand.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_title = _clean_text(item.get("title"))
                if not item_title:
                    raise YunxiaoError("Requirement task title is required before creating Yunxiao workitems")
                item_description = _build_requirement_task_description(workflow, requirement, demand, item, operator)
                item_result = _create_yunxiao_single_workitem(
                    workflow,
                    task_config,
                    operator,
                    subject=item_title,
                    description=item_description,
                    parent_identifier=demand_result["workitemIdentifier"],
                    requested_assignee=_clean_text(item.get("ownerName")),
                )
                created_task_ids.append(item_result["workitemIdentifier"])
                demand_items.append(
                    {
                        "itemIndex": item.get("itemIndex"),
                        "title": item_title,
                        "parentDemandIndex": item.get("parentDemandIndex"),
                        "parentDemandTitle": demand_title,
                        "ownerName": _clean_text(item.get("ownerName")),
                        "contentLines": [str(line) for line in item.get("contentLines") or [] if str(line).strip()],
                        "workitemIdentifier": item_result["workitemIdentifier"],
                        "workitemDisplayId": item_result.get("workitemDisplayId"),
                        "category": item_result.get("category"),
                        "workitemTypeIdentifier": item_result.get("workitemTypeIdentifier"),
                        "parentIdentifier": item_result.get("parentIdentifier"),
                        "sprintId": item_result.get("sprintId"),
                    }
                )
    except YunxiaoError as exc:
        raise YunxiaoRequirementTreeError(
            f"Yunxiao requirement tree creation failed: {exc}",
            partial_result=_build_requirement_tree_partial_result(primary_demand, created_demands, created_task_ids),
        ) from exc

    root = primary_demand or created_demands[0]
    root_identifier = root.get("workitemIdentifier")
    root_display_id = root.get("workitemDisplayId")
    return {
        "workitemIdentifier": root_identifier,
        "workitemDisplayId": root_display_id,
        "requestId": root.get("requestId"),
        "projectId": config["projectId"],
        "projectName": config.get("projectName"),
        "organizationId": config["organizationId"],
        "category": root.get("category") or demand_config["category"],
        "workitemTypeIdentifier": root.get("workitemTypeIdentifier") or demand_config["workitemTypeIdentifier"],
        "assignee": root.get("assignee")
        or {
            "name": config.get("assigneeName"),
            "accountId": config.get("assignee"),
            "source": config.get("assigneeSource"),
        },
        "title": root.get("title"),
        "description": root.get("description"),
        "parentIdentifier": root.get("parentIdentifier"),
        "sprintId": root.get("sprintId"),
        "configSource": config.get("configSource"),
        "authType": config.get("authType"),
        "response": root.get("response"),
        "demandCount": len(created_demands),
        "taskCount": len(created_task_ids),
        "demands": created_demands,
        "taskIdentifiers": created_task_ids,
    }


def _build_requirement_tree_partial_result(
    primary_demand: dict[str, Any] | None,
    created_demands: list[dict[str, Any]],
    created_task_ids: list[str],
) -> dict[str, Any]:
    """内部辅助函数：构建requirement树部分结果。"""
    root = primary_demand or (created_demands[0] if created_demands else None)
    result: dict[str, Any] = {
        "demandCount": len(created_demands),
        "taskCount": len(created_task_ids),
        "demands": created_demands,
        "taskIdentifiers": created_task_ids,
    }
    if root:
        result["workitemIdentifier"] = root.get("workitemIdentifier")
        result["workitemDisplayId"] = root.get("workitemDisplayId")
    return result


def _validate_requirement_tree_task_owners(
    workflow: dict[str, Any],
    config: dict[str, Any],
    demands: list[dict[str, Any]],
) -> None:
    """创建需求树前校验显式负责人，避免失败后留下半截云效数据。"""
    project_name = _resolve_project_name(workflow) or _clean_text(config.get("projectName"))
    missing: list[str] = []
    for demand in demands:
        for item in demand.get("items") or []:
            if not isinstance(item, dict):
                continue
            owner_name = _clean_text(item.get("ownerName"))
            if not owner_name or owner_name in missing:
                continue
            member = db.find_yunxiao_project_member(project_name, owner_name)
            if not member:
                missing.append(owner_name)
    if not missing:
        return
    available = _available_project_member_names(project_name)
    suffix = f" Available project members: {', '.join(available)}." if available else ""
    raise YunxiaoError(
        "Yunxiao assignee config missing: "
        f"projectName={project_name or ''}, assignee={', '.join(missing)}. "
        "Configure adapter_yunxiao_member and adapter_yunxiao_project_member_relation "
        "with member_name or yunxiao_account_id."
        f"{suffix}"
    )


def _available_project_member_names(project_name: str | None) -> list[str]:
    """列出项目成员姓名用于错误提示。"""
    names: list[str] = []
    for member in db.list_yunxiao_project_members(_clean_text(project_name)):
        name = _clean_text(member.get("name")) or _clean_text(member.get("accountId"))
        if name and name not in names:
            names.append(name)
    return names


def _create_yunxiao_single_workitem(
    workflow: dict[str, Any],
    config: dict[str, Any],
    operator: str | None = None,
    *,
    subject: str | None = None,
    description: str | None = None,
    parent_identifier: str | None = None,
    requested_assignee: str | None = None,
) -> dict[str, Any]:
    """内部辅助函数：创建云效单项工作项。"""
    payload = build_create_workitem_payload(
        workflow,
        config,
        operator,
        subject=subject,
        description=description,
        parent_identifier=parent_identifier,
        requested_assignee=requested_assignee,
    )
    response = _request_create_workitem(payload, config)
    _require_api_success(response, "Yunxiao create workitem")
    workitem_id = _extract_workitem_identifier(response)
    if not workitem_id:
        raise YunxiaoError(f"Yunxiao create workitem failed: {_response_error(response)}")
    workitem_display_id = _extract_workitem_display_id(response)
    if not workitem_display_id and config.get("authType") == "personal_token":
        workitem_display_id = _fetch_workitem_display_id_after_create(workitem_id, config)
    assignee = _resolve_workitem_assignee(workflow, config, requested_assignee=requested_assignee)
    return {
        "workitemIdentifier": workitem_id,
        "workitemDisplayId": workitem_display_id,
        "requestId": _pick(response, "requestId", "RequestId"),
        "projectId": config["projectId"],
        "projectName": config.get("projectName"),
        "organizationId": config["organizationId"],
        "category": config["category"],
        "workitemTypeIdentifier": config["workitemTypeIdentifier"],
        "assignee": assignee,
        "title": payload["subject"],
        "description": payload["description"],
        "parentIdentifier": payload.get("parentIdentifier"),
        "sprintId": payload.get("sprint"),
        "configSource": config.get("configSource"),
        "authType": config.get("authType"),
        "response": _safe_response(response),
    }


def _build_requirement_demand_description(
    workflow: dict[str, Any],
    requirement: dict[str, Any],
    demand: dict[str, Any],
    operator: str | None,
) -> str:
    """内部辅助函数：构建requirement需求描述。"""
    lines = [
        "来源：钉钉需求文档",
        f"Workflow：{workflow.get('workflowId') or ''}",
        f"钉钉链接：{workflow.get('dingtalkUrl') or ''}",
        f"需求键：{workflow.get('requirementKey') or ''}",
        f"需求标题：{_clean_text(demand.get('title')) or ''}",
        f"需求描述：{_clean_text(demand.get('description')) or '未提供'}",
        f"操作人：{operator or ''}",
        "",
        "需求摘要：",
        _clean_text(demand.get("title")) or "",
        "",
        "任务清单：",
        _format_requirement_task_list(demand.get("items")),
    ]
    return _clip(_sanitize("\n".join(lines)), 12000)


def _build_requirement_task_description(
    workflow: dict[str, Any],
    requirement: dict[str, Any],
    demand: dict[str, Any],
    item: dict[str, Any],
    operator: str | None,
) -> str:
    """构建云效任务描述：只展示钉钉文档中该任务的主要内容。"""
    return _clip(_sanitize(_format_task_content_lines(item.get("contentLines"))), 12000)


def _format_requirement_demands(value: Any) -> str:
    """内部辅助函数：formatrequirementdemands。"""
    if not isinstance(value, list) or not value:
        return "- 未提供"
    lines: list[str] = []
    for demand in value:
        if not isinstance(demand, dict):
            lines.append(f"- {demand}")
            continue
        demand_title = _clean_text(demand.get("title")) or "未命名需求"
        demand_description = _clean_text(demand.get("description"))
        header = f"- {demand_title}"
        if demand_description:
            header = f"{header}｜{demand_description}"
        lines.append(header)
        items = demand.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                lines.append(f"  - {item}")
                continue
            item_title = _clean_text(item.get("title")) or "未命名任务"
            owner_name = _clean_text(item.get("ownerName"))
            content_lines = item.get("contentLines") or []
            item_header = f"  - {item_title}"
            if owner_name:
                item_header = f"{item_header}｜负责人：{owner_name}"
            lines.append(item_header)
            for content_line in content_lines:
                text = _clean_text(content_line)
                if text:
                    lines.append(f"    - {text}")
    return "\n".join(lines) if lines else "- 未提供"


def _format_requirement_task_list(value: Any) -> str:
    """内部辅助函数：formatrequirement任务列出。"""
    if not isinstance(value, list) or not value:
        return "- 未提供"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        item_title = _clean_text(item.get("title")) or "未命名任务"
        owner_name = _clean_text(item.get("ownerName"))
        header = f"- {item_title}"
        if owner_name:
            header = f"{header}｜负责人：{owner_name}"
        lines.append(header)
    return "\n".join(lines) if lines else "- 未提供"


def _format_task_content_lines(value: Any) -> str:
    """内部辅助函数：format任务contentlines。"""
    if not isinstance(value, list) or not value:
        return "未提供"
    return "\n".join(_clip(_sanitize(str(item)), 500) for item in value if item not in (None, ""))


def _format_list(value: Any) -> str:
    """内部辅助函数：format列出。"""
    if not isinstance(value, list) or not value:
        return "- 未提供"
    return "\n".join(f"- {_clip(_sanitize(str(item)), 500)}" for item in value if item not in (None, ""))


def _format_api_changes(value: Any) -> str:
    """内部辅助函数：formatAPIchanges。"""
    if not isinstance(value, list) or not value:
        return "- 未提供"
    lines = []
    for item in value:
        if isinstance(item, dict):
            method = str(item.get("method") or "").upper()
            path = str(item.get("path") or "")
            description = item.get("description") or item.get("summary") or item.get("name") or ""
            lines.append(f"- {method} {path} {description}".strip())
        else:
            lines.append(f"- {item}")
    return "\n".join(_clip(_sanitize(line), 500) for line in lines if line)


def _extract_workitem_identifier(response: Any) -> str | None:
    """内部辅助函数：提取工作项identifier。"""
    for source in _dict_candidates(response):
        success = source.get("success")
        identifier = (
            source.get("workitemIdentifier")
            or source.get("identifier")
            or source.get("workitemId")
            or source.get("id")
        )
        if isinstance(identifier, (dict, list)):
            continue
        text = _clean_text(identifier)
        if text and (success is None or _is_success(success)):
            return text
    return None


def _fetch_workitem_display_id_after_create(workitem_id: str, config: dict[str, Any]) -> str | None:
    """内部辅助函数：fetch工作项展示IDafter创建。"""
    try:
        detail = get_yunxiao_workitem(workitem_id, config)
    except YunxiaoError:
        return None
    return _extract_workitem_display_id(detail)


def _extract_workitem_display_id(response: Any) -> str | None:
    """内部辅助函数：提取工作项展示ID。"""
    display_keys = (
        "workitemDisplayId",
        "yunxiaoTaskDisplayId",
        "serialNumber",
        "serialNo",
        "serialId",
        "displayId",
        "displayID",
        "displayIdentifier",
        "displayValue",
        "workitemSerialNumber",
    )
    for source in _dict_candidates(response):
        for key in display_keys:
            value = _clean_text(source.get(key))
            if value and _looks_like_display_workitem_id(value):
                return value
    return None


def _looks_like_display_workitem_id(value: str) -> bool:
    """内部辅助函数：lookslike展示工作项ID。"""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]{1,15}-\d{1,10}", value.strip()))


def _extract_status_identifier(response: Any) -> str | None:
    """内部辅助函数：提取状态identifier。"""
    for source in _dict_candidates(response):
        for key in ("statusIdentifier", "statusId", "statusID", "status"):
            value = source.get(key)
            if isinstance(value, dict):
                nested = _first_present(value, "identifier", "id", "value")
                if nested:
                    return nested
                continue
            text = _clean_text(value)
            if text:
                return text
        fields = source.get("fieldValueList") or source.get("customFields") or source.get("fieldValues")
        if isinstance(fields, list):
            for item in fields:
                if not isinstance(item, dict):
                    continue
                identifier = _clean_text(
                    item.get("fieldIdentifier") or item.get("identifier") or item.get("propertyKey") or item.get("key")
                )
                if identifier and identifier.lower() in {"status", "statusidentifier", "statusid"}:
                    value = item.get("value") or item.get("fieldValue") or item.get("propertyValue")
                    return _clean_text(value)
    return None


def _extract_status_name(response: Any) -> str | None:
    """内部辅助函数：提取状态name。"""
    for source in _dict_candidates(response):
        for key in ("statusName", "statusDisplayName", "displayStatus", "status"):
            value = source.get(key)
            if isinstance(value, dict):
                nested = _first_present(value, "name", "displayName", "label")
                if nested:
                    return nested
                continue
            text = _clean_text(value)
            if text:
                return text
    return None


def _has_extractable_status(response: Any) -> bool:
    """内部辅助函数：hasextractable状态。"""
    return bool(_extract_status_identifier(response) or _extract_status_name(response))


def _is_workitem_closed(response: Any, config: dict[str, Any]) -> bool:
    """内部辅助函数：is工作项已关闭。"""
    done_status_id = _clean_text(config.get("doneStatusId"))
    status_identifier = _extract_status_identifier(response)
    if done_status_id and status_identifier and status_identifier == done_status_id:
        return True
    status_name = _extract_status_name(response)
    candidates = set(DEFAULT_DONE_STATUS_NAMES)
    for name in _csv(config.get("doneStatusNames")):
        candidates.add(name.lower())
    if status_identifier and status_identifier.lower() in candidates:
        return True
    return bool(status_name and status_name.lower() in candidates)


def _require_api_success(response: Any, action: str) -> None:
    """内部辅助函数：要求APIsuccess。"""
    if _api_success(response):
        return
    raise YunxiaoError(f"{action} failed: {_response_error(response)}")


def _api_success(response: Any) -> bool:
    """内部辅助函数：APIsuccess。"""
    if response in (None, ""):
        return True
    if not isinstance(response, dict):
        return True
    for source in _dict_candidates(response):
        if source.get("success") is not None:
            return _is_success(source.get("success"))
        code = source.get("errorCode") or source.get("errorCodeStr")
        if code:
            return False
        if source.get("error") or source.get("message") or source.get("errorMessage"):
            status = source.get("status") or source.get("statusCode")
            if str(status).isdigit() and int(status) >= 400:
                return False
        if str(source.get("code") or "").lower() in {"error", "failed", "false"}:
            return False
    return True


def _response_error(response: Any) -> str:
    """内部辅助函数：响应错误。"""
    for source in _dict_candidates(response):
        code = source.get("errorCode") or source.get("code") or source.get("error")
        message = source.get("errorMessage") or source.get("message") or source.get("msg")
        if code or message:
            return _clip(_sanitize(f"code={code or ''} message={message or ''}"), 1000)
    return _clip(_sanitize(str(response)), 1000)


def _safe_response(response: Any) -> Any:
    """内部辅助函数：安全响应。"""
    if isinstance(response, dict):
        return {
            key: _safe_response(value)
            for key, value in response.items()
            if not _looks_secret_key(key)
        }
    if isinstance(response, list):
        return [_safe_response(item) for item in response]
    if isinstance(response, str):
        return _sanitize(response)
    return response


def _parse_json(text: str) -> Any:
    """内部辅助函数：解析JSON。"""
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:1000]


def _parse_error_detail(text: str) -> str:
    """内部辅助函数：解析错误详情。"""
    parsed = _parse_json(text)
    if isinstance(parsed, dict):
        return _response_error(parsed)
    return _clip(_sanitize(str(parsed)), 1000)


def _normalize_endpoint(value: str) -> tuple[str, str]:
    """内部辅助函数：归一化endpoint。"""
    raw = str(value or DEFAULT_ENDPOINT).strip().rstrip("/")
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        scheme = parsed.scheme or "https"
        endpoint = parsed.netloc
    else:
        scheme = "https"
        endpoint = raw
    if not endpoint:
        raise YunxiaoError("Yunxiao OpenAPI endpoint is invalid")
    return scheme, endpoint


def _http_header_name(value: str) -> str:
    """内部辅助函数：httpheadername。"""
    if value == "host":
        return "Host"
    return value


def _normalize_header_value(value: str) -> str:
    """内部辅助函数：归一化header值。"""
    return " ".join(str(value or "").strip().split())


def _is_success(value: Any) -> bool:
    """内部辅助函数：issuccess。"""
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _dict_candidates(payload: Any):
    """内部辅助函数：dictcandidates。"""
    if not isinstance(payload, dict):
        return
    yield payload
    for key in ("data", "result", "body", "workitemIdentifier", "identifier", "workitemId", "id"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            yield nested


def _pick(payload: Any, *keys: str, default: Any = None) -> Any:
    """pick。"""
    for source in _dict_candidates(payload):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return default


def _first_present(payload: Any, *keys: str) -> str | None:
    """内部辅助函数：第一个present。"""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = _clean_text(payload.get(key))
        if value:
            return value
    return None


def _first_env(*names: str) -> str | None:
    """内部辅助函数：第一个env。"""
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _parse_timeout(value: str) -> int:
    """内部辅助函数：解析超时。"""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise YunxiaoError("YUNXIAO_OPENAPI_TIMEOUT must be an integer") from exc


def _looks_secret_key(value: Any) -> bool:
    """内部辅助函数：lookssecretkey。"""
    normalized = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return any(keyword.replace("_", "") in normalized for keyword in SECRET_KEYWORDS)


def _csv(value: Any) -> list[str]:
    """csv。"""
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _join(value: Any) -> str:
    """join。"""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return str(value or "")


def _first_item(value: Any) -> str | None:
    """内部辅助函数：第一个条目。"""
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
    return _clean_text(value)


def _repo_name(value: Any) -> str | None:
    """内部辅助函数：reponame。"""
    text = _clean_text(value)
    if not text:
        return None
    parsed = urllib.parse.urlparse(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    name = path.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return _clean_text(name)


def _clean_text(value: Any) -> str | None:
    """内部辅助函数：清洗文本。"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _sanitize(text: str) -> str:
    """sanitize。"""
    return SECRET_RE.sub(r"\1\2***", str(text or ""))


def _clip(text: str, limit: int) -> str:
    """clip。"""
    value = str(text or "")
    return value if len(value) <= limit else value[:limit]
