from __future__ import annotations

import uuid
from typing import Any

from app import db
from app.dingtalk_docs import DingTalkDocError, extract_node_id, read_dingtalk_doc
from app.models import (
    WorkflowAdvanceRequest,
    WorkflowCodingResultRequest,
    WorkflowRequirementRequest,
    WorkflowStartRequest,
)


class WorkflowError(RuntimeError):
    pass


def start_workflow(request: WorkflowStartRequest) -> dict[str, Any]:
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
    workflow = _load_workflow(workflow_id)
    workflow["events"] = db.list_workflow_events(workflow_id, event_limit)
    return workflow


def advance_workflow(workflow_id: str, request: WorkflowAdvanceRequest) -> dict[str, Any]:
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
        return {
            "workflow": workflow,
            "advanced": False,
            "reason": "Yunxiao task creation is not implemented in P0",
            "nextAction": "manual coding or future Yunxiao adapter",
        }
    raise WorkflowError(f"Workflow status cannot advance automatically: {status}")


def submit_requirement(workflow_id: str, request: WorkflowRequirementRequest) -> dict[str, Any]:
    workflow = _load_workflow(workflow_id)
    if workflow["status"] != "DOC_READ":
        raise WorkflowError(f"Workflow status is not DOC_READ: {workflow['status']}")
    requirement = {
        "summary": request.summary,
        "acceptanceCriteria": request.acceptance_criteria,
        "affectedRepos": request.affected_repos,
        "apiChanges": request.api_changes,
        "testScope": request.test_scope,
        "risk": request.risk,
        "openQuestions": request.open_questions,
        "extra": request.extra,
    }
    context = _merge_context(workflow, {"requirement": requirement})
    updated = db.update_workflow_requirement(
        workflow_id=workflow_id,
        context=context,
        operator=_clean_text(request.operator),
        event_payload={"summary": request.summary, "apiChangeCount": len(request.api_changes)},
    )
    return {
        "workflow": updated,
        "nextAction": "manual coding or future Yunxiao task creation",
    }


def submit_coding_result(workflow_id: str, request: WorkflowCodingResultRequest) -> dict[str, Any]:
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


def _document_summary(doc: dict[str, Any]) -> dict[str, Any]:
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
    workflow = db.find_workflow_instance(workflow_id)
    if not workflow:
        raise WorkflowError(f"Workflow not found: {workflow_id}")
    return workflow


def _merge_context(workflow: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    context = dict(workflow.get("context") or {})
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(context.get(key), dict):
            context[key] = {**context[key], **value}
        else:
            context[key] = value
    return context


def _new_workflow_id() -> str:
    return "wf-" + uuid.uuid4().hex[:16]


def _clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
