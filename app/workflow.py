from __future__ import annotations

import uuid
import re
from typing import Any

from app import db
from app.dingtalk_docs import DingTalkDocError, extract_node_id, read_dingtalk_doc
from app.models import (
    WorkflowAdvanceRequest,
    WorkflowCodingResultRequest,
    WorkflowRequirementRequest,
    WorkflowResolveRequest,
    WorkflowRetryRequest,
    WorkflowStartRequest,
)
from app.yunxiao import YunxiaoCloseSkipped, YunxiaoError, close_yunxiao_workitem, create_yunxiao_workitem


class WorkflowError(RuntimeError):
    """工作流异常。"""
    pass


PROJECT_SELECTED_TARGET_STATUS = "PROJECT_SELECTED"
RESOLVABLE_TARGET_STATUSES = {"APIFOX_SYNCED", "PIPELINE_SUCCESS", "CODING_REQUESTED", PROJECT_SELECTED_TARGET_STATUS}
RETRYABLE_TARGET_STATUSES = {"CODING_REQUESTED"}


def start_workflow(request: WorkflowStartRequest) -> dict[str, Any]:
    """start工作流。"""
    dingtalk_url = request.dingtalk_url.strip()
    if not dingtalk_url:
        raise WorkflowError("dingtalkUrl is required")
    try:
        node_id = extract_node_id(url=dingtalk_url)
    except DingTalkDocError as exc:
        raise WorkflowError(str(exc)) from exc

    workflow_id = _new_workflow_id()
    context = {
        **(request.context or {}),
        "dingtalk": {
            "url": dingtalk_url,
            "nodeId": node_id,
        },
    }
    try:
        return db.create_workflow_instance(
            workflow_id=workflow_id,
            requirement_key=_clean_text(request.requirement_key),
            dingtalk_url=dingtalk_url,
            dingtalk_node_id=node_id,
            repo_url=_clean_text(request.repo_url),
            branch_name=_clean_text(request.branch_name),
            context=context,
            created_by=_clean_text(request.operator),
        )
    except RuntimeError as exc:
        raise WorkflowError(str(exc)) from exc


def get_workflow(workflow_id: str, event_limit: int = 50) -> dict[str, Any]:
    """获取工作流。"""
    workflow = _load_workflow(workflow_id)
    workflow["events"] = db.list_workflow_events(workflow_id, event_limit)
    return workflow


def advance_workflow(workflow_id: str, request: WorkflowAdvanceRequest) -> dict[str, Any]:
    """推进工作流。"""
    workflow = _load_workflow(workflow_id)
    status = workflow["status"]
    if status == "CREATED":
        return _advance_created_to_doc_read(workflow, request)
    if status == "DOC_READ":
        return {
            "workflow": workflow,
            "advanced": False,
            "reason": "requirement parsing is waiting for Codex",
            "nextAction": "POST /workflow/{workflow_id}/requirement",
        }
    if status == "REQUIREMENT_PARSED":
        return _advance_requirement_to_yunxiao_task(workflow, request)
    if status == "APIFOX_SYNCED":
        return _advance_apifox_synced_to_yunxiao_closed(workflow, request)
    if status == "YUNXIAO_TASK_CLOSED":
        return {
            "workflow": workflow,
            "advanced": False,
            "existing": True,
            "reason": "workflow already YUNXIAO_TASK_CLOSED",
        }
    raise WorkflowError(f"Workflow status cannot advance automatically: {status}")


def resolve_workflow(workflow_id: str, request: WorkflowResolveRequest) -> dict[str, Any]:
    """解析工作流。"""
    workflow = _load_workflow(workflow_id)
    if workflow["status"] != "NEEDS_HUMAN":
        raise WorkflowError(f"Workflow status is not NEEDS_HUMAN: {workflow['status']}")
    target_status = _clean_text(request.target_status)
    if target_status not in RESOLVABLE_TARGET_STATUSES:
        allowed = ", ".join(sorted(RESOLVABLE_TARGET_STATUSES))
        raise WorkflowError(f"Unsupported resolve targetStatus: {target_status}. Allowed: {allowed}")
    if target_status == PROJECT_SELECTED_TARGET_STATUS:
        return _resolve_project_selection(workflow, request)
    resolved = db.resolve_workflow_needs_human(
        workflow_id=workflow_id,
        target_status=target_status,
        operator=_clean_text(request.operator),
        reason=_clean_text(request.reason),
        event_payload={"targetStatus": target_status, "reason": _clean_text(request.reason)},
    )
    return {
        "workflow": resolved,
        "resolved": True,
        "nextAction": _resolve_next_action(target_status),
    }


def retry_workflow(workflow_id: str, request: WorkflowRetryRequest) -> dict[str, Any]:
    """重试工作流。"""
    workflow = _load_workflow(workflow_id)
    if workflow["status"] != "PIPELINE_FAILED":
        raise WorkflowError(f"Workflow status is not PIPELINE_FAILED: {workflow['status']}")
    target_status = _clean_text(request.target_status)
    if target_status not in RETRYABLE_TARGET_STATUSES:
        allowed = ", ".join(sorted(RETRYABLE_TARGET_STATUSES))
        raise WorkflowError(f"Unsupported retry targetStatus: {target_status}. Allowed: {allowed}")
    retry_count = int(workflow.get("retryCount") or 0)
    if retry_count >= request.max_retry_count:
        raise WorkflowError(
            f"Workflow retry count exceeded limit: {workflow_id} ({retry_count}/{request.max_retry_count})"
        )

    reason = _clean_text(request.reason) or "Pipeline failure confirmed, retry coding from CODING_REQUESTED"
    retried = db.retry_workflow_from_pipeline_failed(
        workflow_id=workflow_id,
        target_status=target_status,
        operator=_clean_text(request.operator),
        reason=reason,
        max_retry_count=request.max_retry_count,
        event_payload={
            "targetStatus": target_status,
            "reason": reason,
            "maxRetryCount": request.max_retry_count,
            "previousRetryCount": retry_count,
        },
    )
    return {
        "workflow": retried,
        "retried": True,
        "fromStatus": "PIPELINE_FAILED",
        "targetStatus": target_status,
        "nextAction": _retry_next_action(target_status),
    }


def submit_requirement(workflow_id: str, request: WorkflowRequirementRequest) -> dict[str, Any]:
    """提交requirement。"""
    workflow = _load_workflow(workflow_id)
    if workflow["status"] != "DOC_READ":
        raise WorkflowError(f"Workflow status is not DOC_READ: {workflow['status']}")
    requirement_summary = _derive_requirement_summary(request)
    demands = [_normalize_requirement_demand(demand) for demand in request.demands]
    demands = _apply_trusted_dingtalk_owner_names(workflow, demands)
    requirement = {
        "summary": requirement_summary,
        "documentTitle": _clean_text(request.document_title),
        "version": _clean_text(request.version),
        "sourceUrl": _clean_text(request.source_url),
        "demands": demands,
        "assigneeId": _clean_text(request.assignee_id),
        "assigneeName": _clean_text(request.assignee_name),
        "acceptanceCriteria": request.acceptance_criteria,
        "affectedRepos": request.affected_repos,
        "apiChanges": request.api_changes,
        "testScope": request.test_scope,
        "risk": request.risk,
        "openQuestions": request.open_questions,
        "extra": request.extra,
    }
    project_context = _validate_document_project_name(workflow, requirement)
    if project_context.get("needsHuman"):
        context = _merge_context(workflow, {"requirement": requirement, "projectSelection": project_context["projectSelection"]})
        message = _project_selection_message(project_context["projectSelection"])
        updated = db.mark_workflow_needs_human(
            workflow_id=workflow_id,
            from_status="DOC_READ",
            error=message,
            operator=_clean_text(request.operator),
            event_type="project_selection_required",
            event_payload=project_context["projectSelection"],
            context=context,
        )
        return {
            "workflow": updated,
            "resolved": False,
            "projectSelection": project_context["projectSelection"],
            "nextAction": "POST /workflow/{workflow_id}/resolve with targetStatus=PROJECT_SELECTED and projectName",
        }
    context = _merge_context(workflow, {**project_context, "requirement": requirement})
    updated = db.update_workflow_requirement(
        workflow_id=workflow_id,
        context=context,
        operator=_clean_text(request.operator),
        event_payload={
            "summary": requirement_summary,
            "documentTitle": _clean_text(request.document_title),
            "version": _clean_text(request.version),
            "demandCount": len(demands),
            "taskCount": sum(len(demand.get("items") or []) for demand in demands),
            "apiChangeCount": len(request.api_changes),
        },
    )
    return {
        "workflow": updated,
        "nextAction": "manual coding or future Yunxiao demand/task creation",
    }


def _derive_requirement_summary(request: WorkflowRequirementRequest) -> str:
    """内部辅助函数：deriverequirement摘要。"""
    summary = _clean_text(request.summary)
    if summary:
        return summary
    document_title = _clean_text(request.document_title)
    if document_title:
        return document_title
    if request.demands:
        first_demand = request.demands[0]
        demand_title = _clean_text(first_demand.title)
        if demand_title:
            return demand_title
        if first_demand.items:
            first_item_title = _clean_text(first_demand.items[0].title)
            if first_item_title:
                return first_item_title
    return ""


def _validate_document_project_name(workflow: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]:
    """校验钉钉文档项目名必须来自云效项目配置。"""
    trusted_document_project_name = _trusted_dingtalk_document_project_name(workflow)
    submitted_document_project_name = _submitted_document_project_name(requirement)
    if trusted_document_project_name and submitted_document_project_name:
        if _normalize_project_name(trusted_document_project_name) != _normalize_project_name(submitted_document_project_name):
            raise WorkflowError(
                "DingTalk document projectName mismatch: "
                f"readProjectName={trusted_document_project_name}, submittedProjectName={submitted_document_project_name}. "
                "Use the projectName from the Adapter DingTalk read result and do not infer from old context."
            )
    document_project_name = trusted_document_project_name or submitted_document_project_name or _context_project_name(workflow)
    if not document_project_name:
        return {}
    project_config = db.find_yunxiao_project_config(document_project_name)
    if project_config:
        project_name = _clean_text(project_config.get("projectName")) or document_project_name
        return {
            "projectName": project_name,
            "sourceProjectName": document_project_name,
        }
    candidates = _yunxiao_project_candidates(document_project_name)
    return {
        "needsHuman": True,
        "projectSelection": {
            "reason": "项目名未精确匹配 adapter_yunxiao_project_config",
            "documentProjectName": document_project_name,
            "candidates": candidates,
            "nextAction": "请选择一个云效项目后继续",
        },
    }


def _apply_trusted_dingtalk_owner_names(workflow: dict[str, Any], demands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从钉钉原文回填任务负责人，避免结构化漏掉 ownerName 后落到默认负责人。"""
    task_owners = _trusted_dingtalk_task_owners(workflow)
    if not task_owners:
        return demands
    normalized_demands: list[dict[str, Any]] = []
    for demand in demands:
        copied_demand = dict(demand)
        items: list[dict[str, Any]] = []
        for item in demand.get("items") or []:
            copied_item = dict(item)
            title = _clean_text(copied_item.get("title"))
            trusted_owner = task_owners.get(_normalize_project_name(title))
            submitted_owner = _clean_text(copied_item.get("ownerName"))
            if trusted_owner and submitted_owner:
                if _normalize_project_name(trusted_owner) != _normalize_project_name(submitted_owner):
                    raise WorkflowError(
                        "DingTalk task owner mismatch: "
                        f"taskTitle={title}, readOwnerName={trusted_owner}, submittedOwnerName={submitted_owner}. "
                        "Use the ownerName from the Adapter DingTalk read result."
                    )
            if trusted_owner and not submitted_owner:
                copied_item["ownerName"] = trusted_owner
            items.append(copied_item)
        copied_demand["items"] = items
        normalized_demands.append(copied_demand)
    return normalized_demands


def _trusted_dingtalk_task_owners(workflow: dict[str, Any]) -> dict[str, str]:
    """从 Adapter 已读取的钉钉原文中提取任务标题到负责人的映射。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    dingtalk = context.get("dingtalk") if isinstance(context.get("dingtalk"), dict) else {}
    read = dingtalk.get("read") if isinstance(dingtalk.get("read"), dict) else {}
    document = read.get("document") if isinstance(read.get("document"), dict) else {}
    result = document.get("result") if isinstance(document.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), list) else []
    owners: dict[str, str] = {}
    current_task_title = ""
    for block in data:
        if not isinstance(block, dict):
            continue
        heading = block.get("heading") if isinstance(block.get("heading"), dict) else {}
        paragraph = block.get("paragraph") if isinstance(block.get("paragraph"), dict) else {}
        if heading:
            title = _clean_task_heading_text(heading.get("text"))
            level = _clean_text(heading.get("level"))
            if title and level in {"heading-5", "5"}:
                current_task_title = title
            elif level in {"heading-4", "4"}:
                current_task_title = ""
            continue
        text = _clean_text(paragraph.get("text")) if paragraph else ""
        if not current_task_title or not text:
            continue
        owner = _extract_labeled_value(text, "负责人")
        if owner:
            owners.setdefault(_normalize_project_name(current_task_title), owner)
    return owners


def _clean_task_heading_text(value: Any) -> str:
    """清理钉钉任务标题中的序号。"""
    text = _clean_text(value)
    text = re.sub(r"^\s*\d+\s*[.．、]\s*", "", text)
    return _clean_text(text.rstrip("：:"))


def _resolve_project_selection(workflow: dict[str, Any], request: WorkflowResolveRequest) -> dict[str, Any]:
    """确认人工选择的云效项目并恢复到需求已解析状态。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    selection = context.get("projectSelection") if isinstance(context.get("projectSelection"), dict) else {}
    requirement = context.get("requirement") if isinstance(context.get("requirement"), dict) else {}
    selected = _selected_project_config(request, selection)
    if not selected:
        candidates = selection.get("candidates") if isinstance(selection.get("candidates"), list) else []
        candidate_names = [_clean_text(item.get("projectName")) for item in candidates if isinstance(item, dict)]
        suffix = f" Candidates: {', '.join(name for name in candidate_names if name)}." if candidate_names else ""
        raise WorkflowError(
            "Selected Yunxiao project is not configured or not in current project candidates: "
            f"projectName={_clean_text(request.project_name)}, projectId={_clean_text(request.project_id)}.{suffix}"
        )
    project_name = _clean_text(selected.get("projectName"))
    document_project_name = _clean_text(selection.get("documentProjectName")) or project_name
    updated_context = {
        **context,
        "projectName": project_name,
        "sourceProjectName": document_project_name,
        "projectSelection": {
            **selection,
            "selectedProjectName": project_name,
            "selectedProjectId": _clean_text(selected.get("projectId")),
            "resolved": True,
        },
        "requirement": {
            **requirement,
            "extra": {
                **(requirement.get("extra") if isinstance(requirement.get("extra"), dict) else {}),
                "documentProjectName": document_project_name,
                "sourceProjectName": document_project_name,
                "selectedYunxiaoProjectName": project_name,
            },
        },
    }
    resolved = db.resolve_workflow_needs_human(
        workflow_id=workflow["workflowId"],
        target_status="REQUIREMENT_PARSED",
        operator=_clean_text(request.operator),
        reason=_clean_text(request.reason) or f"Yunxiao project selected: {project_name}",
        event_payload={
            "targetStatus": PROJECT_SELECTED_TARGET_STATUS,
            "resolvedStatus": "REQUIREMENT_PARSED",
            "projectName": project_name,
            "projectId": _clean_text(selected.get("projectId")),
            "documentProjectName": document_project_name,
        },
        context=updated_context,
    )
    return {
        "workflow": resolved,
        "resolved": True,
        "targetStatus": PROJECT_SELECTED_TARGET_STATUS,
        "resolvedStatus": "REQUIREMENT_PARSED",
        "nextAction": _resolve_next_action(PROJECT_SELECTED_TARGET_STATUS),
    }


def _selected_project_config(request: WorkflowResolveRequest, selection: dict[str, Any]) -> dict[str, Any] | None:
    """从用户确认的项目名或projectId解析云效项目配置。"""
    requested_name = _clean_text(request.project_name)
    requested_id = _clean_text(request.project_id)
    candidates = selection.get("candidates") if isinstance(selection.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_name = _clean_text(candidate.get("projectName"))
        candidate_id = _clean_text(candidate.get("projectId"))
        if requested_name and _normalize_project_name(candidate_name) == _normalize_project_name(requested_name):
            return candidate
        if requested_id and candidate_id and candidate_id == requested_id:
            return candidate
    if requested_name:
        config = db.find_yunxiao_project_config(requested_name)
        if config:
            return config
    return None


def _project_selection_message(selection: dict[str, Any]) -> str:
    """生成人工选择项目时的错误提示。"""
    document_project_name = _clean_text(selection.get("documentProjectName"))
    candidates = selection.get("candidates") if isinstance(selection.get("candidates"), list) else []
    names = [_clean_text(item.get("projectName")) for item in candidates if isinstance(item, dict)]
    suffix = f" Candidates: {', '.join(name for name in names if name)}." if names else ""
    return (
        "DingTalk document projectName is not configured in adapter_yunxiao_project_config: "
        f"projectName={document_project_name}. Please choose a Yunxiao project to continue.{suffix}"
    )


def _document_project_name(workflow: dict[str, Any], requirement: dict[str, Any]) -> str:
    """提取钉钉文档中声明的项目名。"""
    return _trusted_dingtalk_document_project_name(workflow) or _submitted_document_project_name(requirement) or _context_project_name(workflow)


def _submitted_document_project_name(requirement: dict[str, Any]) -> str:
    """提取结构化提交里的项目名。"""
    extra = requirement.get("extra") if isinstance(requirement.get("extra"), dict) else {}
    for source in (extra, requirement):
        if not isinstance(source, dict):
            continue
        for key in (
            "sourceProjectName",
            "documentProjectName",
            "dingtalkProjectName",
            "yunxiaoProjectName",
            "projectName",
            "project_name",
        ):
            value = _clean_text(source.get(key))
            if value:
                return value
    return ""


def _context_project_name(workflow: dict[str, Any]) -> str:
    """提取 workflow 上下文里的项目名。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    for key in ("sourceProjectName", "documentProjectName", "projectName", "project_name"):
        value = _clean_text(context.get(key))
        if value:
            return value
    return ""


def _trusted_dingtalk_document_project_name(workflow: dict[str, Any]) -> str:
    """从 Adapter 已读取的钉钉原文中提取项目名，作为服务端可信来源。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    dingtalk = context.get("dingtalk") if isinstance(context.get("dingtalk"), dict) else {}
    read = dingtalk.get("read") if isinstance(dingtalk.get("read"), dict) else {}
    document = read.get("document") if isinstance(read.get("document"), dict) else {}
    for text in _dingtalk_document_texts(document):
        value = _extract_labeled_value(text, "项目名")
        if value:
            return value
    return ""


def _dingtalk_document_texts(document: dict[str, Any]) -> list[str]:
    """提取钉钉文档块文本。"""
    result = document.get("result") if isinstance(document.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), list) else []
    texts: list[str] = []
    for block in data:
        if not isinstance(block, dict):
            continue
        for key in ("paragraph", "heading"):
            value = block.get(key)
            if isinstance(value, dict):
                text = _clean_text(value.get("text"))
                if text:
                    texts.append(text)
    return texts


def _extract_labeled_value(text: str, label: str) -> str:
    """提取形如 `项目名：园务` 的字段值。"""
    raw = _clean_text(text)
    if not raw:
        return ""
    match = re.match(rf"^\s*{re.escape(label)}\s*[:：]\s*(.+?)\s*$", raw)
    return _clean_text(match.group(1)) if match else ""


def _normalize_project_name(value: str) -> str:
    """归一化项目名用于一致性校验。"""
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _available_yunxiao_project_names() -> list[str]:
    """列出可用于钉钉文档项目名校验的云效项目名。"""
    names: list[str] = []
    for config in db.list_yunxiao_project_configs():
        name = _clean_text(config.get("projectName"))
        if name and name not in names:
            names.append(name)
    return names


def _yunxiao_project_candidates(document_project_name: str) -> list[dict[str, Any]]:
    """根据文档项目名给出云效项目候选。"""
    configs = db.list_yunxiao_project_configs()
    normalized_document = _normalize_project_name(document_project_name)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    fallback: list[dict[str, Any]] = []
    for index, config in enumerate(configs):
        name = _clean_text(config.get("projectName"))
        if not name:
            continue
        candidate = {
            "projectName": name,
            "projectId": _clean_text(config.get("projectId")),
            "projectConfigId": config.get("projectConfigId"),
            "remark": _clean_text(config.get("remark")),
        }
        fallback.append(candidate)
        normalized_name = _normalize_project_name(name)
        if normalized_document and normalized_document in normalized_name:
            scored.append((0, index, candidate))
        elif normalized_document and normalized_name in normalized_document:
            scored.append((1, index, candidate))
        elif normalized_document and any(char in normalized_name for char in normalized_document):
            scored.append((2, index, candidate))
    selected = [item for _, _, item in sorted(scored, key=lambda row: (row[0], row[1]))]
    return selected[:10] if selected else fallback[:10]


def _normalize_requirement_demand(demand: Any) -> dict[str, Any]:
    """内部辅助函数：归一化requirement需求。"""
    if hasattr(demand, "model_dump"):
        raw = demand.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(demand, dict):
        raw = dict(demand)
    else:
        raw = {}
    items: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        if hasattr(item, "model_dump"):
            item_raw = item.model_dump(by_alias=True, exclude_none=True)
        elif isinstance(item, dict):
            item_raw = dict(item)
        else:
            item_raw = {}
        items.append(
            {
                "itemIndex": item_raw.get("itemIndex"),
                "title": _clean_text(item_raw.get("title")),
                "parentDemandIndex": item_raw.get("parentDemandIndex"),
                "parentDemandTitle": _clean_text(item_raw.get("parentDemandTitle")) or _clean_text(raw.get("title")),
                "ownerName": _clean_text(item_raw.get("ownerName")),
                "contentLines": [str(line) for line in item_raw.get("contentLines") or [] if str(line).strip()],
            }
        )
    return {
        "demandIndex": raw.get("demandIndex"),
        "title": _clean_text(raw.get("title")),
        "description": _clean_text(raw.get("description")),
        "items": items,
    }


def submit_coding_result(workflow_id: str, request: WorkflowCodingResultRequest) -> dict[str, Any]:
    """提交编码结果。"""
    workflow = _load_workflow(workflow_id)
    if workflow["status"] not in {"REQUIREMENT_PARSED", "CODING_REQUESTED"}:
        raise WorkflowError(f"Workflow status cannot accept coding result: {workflow['status']}")
    coding_result = {
        "branchName": request.branch_name or workflow.get("branchName"),
        "commitId": request.commit_id,
        "mergeRequestUrl": request.merge_request_url,
        "summary": request.summary,
        "tests": request.tests,
        "extra": request.extra,
    }
    context = _merge_context(workflow, {"codingResult": coding_result})
    updated = db.update_workflow_coding_result(
        workflow_id=workflow_id,
        from_status=workflow["status"],
        branch_name=_clean_text(request.branch_name),
        commit_id=_clean_text(request.commit_id),
        context=context,
        operator=_clean_text(request.operator),
        event_payload={
            "branchName": coding_result["branchName"],
            "commitId": coding_result["commitId"],
            "mergeRequestUrl": coding_result["mergeRequestUrl"],
        },
    )
    return {
        "workflow": updated,
        "nextAction": "wait for Yunxiao pipeline callback",
    }


def _advance_created_to_doc_read(workflow: dict[str, Any], request: WorkflowAdvanceRequest) -> dict[str, Any]:
    """内部辅助函数：推进已创建to文档读取。"""
    workflow_id = workflow["workflowId"]
    try:
        doc = read_dingtalk_doc(
            url=workflow["dingtalkUrl"],
            node_id=workflow.get("dingtalkNodeId"),
            sheet_id=request.sheet_id,
            workbook_id=request.workbook_id,
            cell_range=request.range,
            timeout=request.timeout,
            config_name=request.config_name,
            kind=request.kind,
        )
    except DingTalkDocError as exc:
        failed = db.record_workflow_error(
            workflow_id=workflow_id,
            status="CREATED",
            error=str(exc),
            operator=_clean_text(request.operator),
            event_type="doc_read_failed",
            event_payload={"step": "doc_read"},
        )
        raise WorkflowError(f"DingTalk document read failed: {failed['lastError']}") from exc

    summary = _document_summary(doc)
    context = _merge_context(
        workflow,
        {
            "dingtalk": {
                **(workflow.get("context", {}).get("dingtalk") or {}),
                "read": summary,
            }
        },
    )
    updated = db.update_workflow_doc_read(
        workflow_id=workflow_id,
        from_status="CREATED",
        context=context,
        operator=_clean_text(request.operator),
        event_payload=summary,
    )
    return {
        "workflow": updated,
        "document": summary,
        "nextAction": "Codex should parse requirement and POST /workflow/{workflow_id}/requirement",
    }


def _advance_requirement_to_yunxiao_task(workflow: dict[str, Any], request: WorkflowAdvanceRequest) -> dict[str, Any]:
    """内部辅助函数：推进requirementto云效任务。"""
    workflow_id = workflow["workflowId"]
    if workflow.get("yunxiaoTaskId"):
        return {
            "workflow": workflow,
            "advanced": False,
            "existing": True,
            "reason": "Yunxiao workitem already exists",
            "nextAction": "Codex should start coding and POST /workflow/{workflow_id}/coding-result",
        }

    try:
        result = create_yunxiao_workitem(workflow, _clean_text(request.operator))
    except YunxiaoError as exc:
        partial_result = getattr(exc, "partial_result", None)
        failed = db.record_workflow_error(
            workflow_id=workflow_id,
            status="REQUIREMENT_PARSED",
            error=str(exc),
            operator=_clean_text(request.operator),
            event_type="yunxiao_workitem_create_failed",
            event_payload={
                "step": "yunxiao_workitem_create",
                **({"partialResult": partial_result} if partial_result else {}),
            },
        )
        raise WorkflowError(f"Yunxiao workitem creation failed: {failed['lastError']}") from exc

    context = _merge_context(
        workflow,
        {
            "yunxiao": {
                "createResult": {
                    "workitemIdentifier": result["workitemIdentifier"],
                    "workitemDisplayId": result.get("workitemDisplayId"),
                    "requestId": result.get("requestId"),
                    "projectName": result.get("projectName"),
                    "projectId": result.get("projectId"),
                    "category": result.get("category"),
                    "workitemTypeIdentifier": result.get("workitemTypeIdentifier"),
                    "assignee": result.get("assignee"),
                    "title": result.get("title"),
                    "description": result.get("description"),
                    "parentIdentifier": result.get("parentIdentifier"),
                    "sprintId": result.get("sprintId"),
                    "demandCount": result.get("demandCount"),
                    "taskCount": result.get("taskCount"),
                    "demands": result.get("demands"),
                    "taskIdentifiers": result.get("taskIdentifiers"),
                    "configSource": result.get("configSource"),
                }
            }
        },
    )
    created = db.update_workflow_yunxiao_task_created(
        workflow_id=workflow_id,
        from_status="REQUIREMENT_PARSED",
        yunxiao_task_id=result["workitemIdentifier"],
        context=context,
        operator=_clean_text(request.operator),
        event_payload={
            "yunxiaoTaskId": result["workitemIdentifier"],
            "yunxiaoTaskDisplayId": result.get("workitemDisplayId"),
            "demandCount": result.get("demandCount"),
            "taskCount": result.get("taskCount"),
            "projectName": result.get("projectName"),
            "projectId": result.get("projectId"),
            "assignee": result.get("assignee"),
            "title": result.get("title"),
        },
    )
    coding_context = _merge_context(
        created,
        {
            "codingRequest": {
                "source": "yunxiao_workitem_created",
                "yunxiaoTaskId": result["workitemIdentifier"],
                "yunxiaoTaskDisplayId": result.get("workitemDisplayId"),
                "demandCount": result.get("demandCount"),
                "taskCount": result.get("taskCount"),
                "taskIdentifiers": result.get("taskIdentifiers"),
                "assignee": result.get("assignee"),
            }
        },
    )
    updated = db.update_workflow_coding_requested(
        workflow_id=workflow_id,
        context=coding_context,
        operator=_clean_text(request.operator),
        event_payload={
            "yunxiaoTaskId": result["workitemIdentifier"],
            "yunxiaoTaskDisplayId": result.get("workitemDisplayId"),
        },
    )
    return {
        "workflow": updated,
        "advanced": True,
        "yunxiao": {
            "workitemIdentifier": result["workitemIdentifier"],
            "workitemDisplayId": result.get("workitemDisplayId"),
            "projectName": result.get("projectName"),
            "projectId": result.get("projectId"),
        },
        "nextAction": "Codex should start coding and POST /workflow/{workflow_id}/coding-result",
    }


def _advance_apifox_synced_to_yunxiao_closed(
    workflow: dict[str, Any],
    request: WorkflowAdvanceRequest,
) -> dict[str, Any]:
    """内部辅助函数：推进Apifoxsyncedto云效已关闭。"""
    workflow_id = workflow["workflowId"]
    try:
        result = close_yunxiao_workitem(
            workflow,
            _clean_text(request.operator),
            explicit_refs=request.close_task_refs or None,
        )
    except YunxiaoCloseSkipped as exc:
        return {
            "workflow": workflow,
            "advanced": False,
            "reason": str(exc),
            "nextAction": "add explicit Yunxiao task ids in commit message before closing",
        }
    except YunxiaoError as exc:
        failed = db.mark_workflow_needs_human(
            workflow_id=workflow_id,
            from_status="APIFOX_SYNCED",
            error=str(exc),
            operator=_clean_text(request.operator),
            event_type="yunxiao_workitem_close_failed",
            event_payload={
                "step": "yunxiao_workitem_close",
                "yunxiaoTaskId": workflow.get("yunxiaoTaskId"),
            },
        )
        raise WorkflowError(f"Yunxiao workitem close failed: {failed['lastError']}") from exc

    context = _merge_context(
        workflow,
        {
            "yunxiao": {
                **((workflow.get("context") or {}).get("yunxiao") or {}),
                "closeResult": {
                    "workitemIdentifier": result["workitemIdentifier"],
                    "workitemDisplayId": result.get("workitemDisplayId"),
                    "alreadyClosed": result.get("alreadyClosed"),
                    "closedStatus": result.get("closedStatus"),
                    "closedStatusName": result.get("closedStatusName"),
                    "writeback": result.get("writeback"),
                    "closedTaskIds": result.get("closedTaskIds"),
                    "skippedTaskIds": result.get("skippedTaskIds"),
                    "results": result.get("results"),
                    "configSource": result.get("configSource"),
                },
            }
        },
    )
    event_type = "yunxiao_workitem_close_skipped" if result.get("alreadyClosed") else "yunxiao_workitem_closed"
    message = "Yunxiao workitem already closed" if result.get("alreadyClosed") else "Yunxiao workitem closed"
    updated = db.update_workflow_yunxiao_task_closed(
        workflow_id=workflow_id,
        context=context,
        operator=_clean_text(request.operator),
        event_type=event_type,
        message=message,
        event_payload={
            "yunxiaoTaskId": result["workitemIdentifier"],
            "yunxiaoTaskDisplayId": result.get("workitemDisplayId"),
            "closedStatus": result.get("closedStatus"),
            "closedStatusName": result.get("closedStatusName"),
            "alreadyClosed": result.get("alreadyClosed"),
            "writeback": result.get("writeback"),
            "closedTaskIds": result.get("closedTaskIds"),
            "skippedTaskIds": result.get("skippedTaskIds"),
        },
    )
    return {
        "workflow": updated,
        "advanced": True,
        "yunxiao": {
            "workitemIdentifier": result["workitemIdentifier"],
            "workitemDisplayId": result.get("workitemDisplayId"),
            "alreadyClosed": result.get("alreadyClosed"),
            "closedStatus": result.get("closedStatus"),
            "closedStatusName": result.get("closedStatusName"),
            "writeback": result.get("writeback"),
            "closedTaskIds": result.get("closedTaskIds"),
            "skippedTaskIds": result.get("skippedTaskIds"),
        },
        "nextAction": "delivery workflow is complete",
    }


def _document_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：文档摘要。"""
    kind = doc.get("kind")
    summary: dict[str, Any] = {
        "ok": bool(doc.get("ok")),
        "nodeId": doc.get("nodeId"),
        "extension": doc.get("extension"),
        "kind": kind,
        "configName": doc.get("configName"),
        "metadata": doc.get("metadata") or {},
    }
    if kind == "sheet":
        range_result = doc.get("rangeResult")
        summary.update(
            {
                "workbookId": doc.get("workbookId"),
                "sheetId": doc.get("sheetId"),
                "range": doc.get("range"),
                "sheets": doc.get("sheets") or [],
                "rangeResult": range_result,
            }
        )
        return summary
    summary.update(
        {
            "documentId": doc.get("documentId"),
            "document": doc.get("document"),
        }
    )
    return summary


def _load_workflow(workflow_id: str) -> dict[str, Any]:
    """内部辅助函数：加载工作流。"""
    workflow = db.find_workflow_instance(workflow_id)
    if not workflow:
        raise WorkflowError(f"Workflow not found: {workflow_id}")
    return workflow


def _resolve_next_action(target_status: str) -> str:
    """内部辅助函数：解析下一步action。"""
    if target_status == PROJECT_SELECTED_TARGET_STATUS:
        return "POST /workflow/{workflow_id}/advance to create Yunxiao requirement/task"
    if target_status == "APIFOX_SYNCED":
        return "POST /workflow/{workflow_id}/advance to retry Yunxiao close/writeback"
    if target_status == "PIPELINE_SUCCESS":
        return "retry Apifox sync through Yunxiao flow-event callback"
    if target_status == "CODING_REQUESTED":
        return "continue coding and POST /workflow/{workflow_id}/coding-result"
    return "inspect workflow and continue manually"


def _retry_next_action(target_status: str) -> str:
    """内部辅助函数：重试下一步action。"""
    if target_status == "CODING_REQUESTED":
        return "Codex should repair the failure and POST /workflow/{workflow_id}/coding-result"
    return "inspect workflow and continue manually"


def _merge_context(workflow: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：merge上下文。"""
    context = dict(workflow.get("context") or {})
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(context.get(key), dict):
            context[key] = {**context[key], **value}
        else:
            context[key] = value
    return context


def _new_workflow_id() -> str:
    """内部辅助函数：new工作流ID。"""
    return "wf-" + uuid.uuid4().hex[:16]


def _clean_text(value: Any) -> str | None:
    """内部辅助函数：清洗文本。"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
