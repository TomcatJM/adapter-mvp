from __future__ import annotations

from typing import Any

from app import db
from app.apifox import maybe_import_from_flow_event
from app.models import YunxiaoPipelineFailureCallback


PIPELINE_SUCCESS_FROM_STATUSES = {"CODE_SUBMITTED", "PIPELINE_RUNNING"}
PIPELINE_FAILURE_FROM_STATUSES = {"CODE_SUBMITTED", "PIPELINE_RUNNING", "PIPELINE_SUCCESS"}


def handle_pipeline_success(payload: dict[str, Any], callback: YunxiaoPipelineFailureCallback) -> dict[str, Any]:
    workflow_id = _workflow_id_from_payload(payload, callback)
    if not workflow_id:
        apifox = maybe_import_from_flow_event(payload)
        return {
            "workflow": {
                "bound": False,
                "reason": "missing WORKFLOW_ID",
            },
            "apifox": apifox,
        }

    workflow = db.find_workflow_instance(workflow_id)
    if not workflow:
        return {
            "workflow": {
                "bound": False,
                "workflowId": workflow_id,
                "reason": "workflow not found",
            },
            "apifox": {"enabled": False, "imported": False, "reason": "workflow not found"},
        }

    status = workflow["status"]
    if status == "APIFOX_SYNCED":
        return {
            "workflow": {
                "bound": True,
                "advanced": False,
                "workflow": workflow,
                "reason": "workflow already APIFOX_SYNCED",
            },
            "apifox": {"enabled": False, "imported": False, "reason": "workflow already APIFOX_SYNCED"},
        }
    if status not in PIPELINE_SUCCESS_FROM_STATUSES and status != "PIPELINE_SUCCESS":
        return {
            "workflow": {
                "bound": True,
                "advanced": False,
                "workflow": workflow,
                "reason": f"workflow status cannot accept pipeline success: {status}",
            },
            "apifox": {"enabled": False, "imported": False, "reason": "workflow status cannot accept pipeline success"},
        }

    if status != "PIPELINE_SUCCESS":
        workflow = _mark_pipeline_success(workflow, callback)

    apifox = maybe_import_from_flow_event(payload)
    context = _merge_context(workflow, {"apifox": {"lastResult": apifox}})
    if apifox.get("imported") is True:
        workflow = db.update_workflow_apifox_synced(
            workflow_id=workflow["workflowId"],
            context=context,
            apifox_project_id=_clean_text(apifox.get("projectId")),
            operator=callback.operator,
            event_payload=_apifox_event_payload(apifox),
        )
        return {
            "workflow": {
                "bound": True,
                "advanced": True,
                "workflow": workflow,
                "apifoxSynced": True,
            },
            "apifox": apifox,
        }

    workflow = db.record_workflow_apifox_result(
        workflow_id=workflow["workflowId"],
        status="PIPELINE_SUCCESS",
        context=context,
        operator=callback.operator,
        event_type=_apifox_event_type(apifox),
        message=str(apifox.get("reason") or "Apifox import did not finish"),
        event_payload=_apifox_event_payload(apifox),
    )
    return {
        "workflow": {
            "bound": True,
            "advanced": True,
            "workflow": workflow,
            "apifoxSynced": False,
        },
        "apifox": apifox,
    }


def handle_pipeline_failure(callback: YunxiaoPipelineFailureCallback, analysis: dict[str, Any]) -> dict[str, Any]:
    workflow_id = _workflow_id_from_callback(callback)
    if not workflow_id:
        return {
            "bound": False,
            "reason": "missing WORKFLOW_ID",
        }

    workflow = db.find_workflow_instance(workflow_id)
    if not workflow:
        return {
            "bound": False,
            "workflowId": workflow_id,
            "reason": "workflow not found",
        }

    status = workflow["status"]
    if status == "PIPELINE_FAILED":
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "reason": "workflow already PIPELINE_FAILED",
        }
    if status not in PIPELINE_FAILURE_FROM_STATUSES:
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "reason": f"workflow status cannot accept pipeline failure: {status}",
        }

    context = _merge_context(
        workflow,
        {
            "pipeline": _pipeline_context(callback),
            "pipelineFailure": {
                "analysis": analysis,
                "logUrl": callback.log_url,
                "exitCode": callback.exit_code,
            },
        },
    )
    updated = db.update_workflow_pipeline_failed(
        workflow_id=workflow["workflowId"],
        from_status=status,
        pipeline_id=callback.pipeline_id,
        build_number=callback.build_number,
        branch_name=_clean_text(callback.branch_name),
        commit_id=_clean_text(callback.commit_id),
        context=context,
        operator=callback.operator,
        error=str(analysis.get("summary") or "Pipeline failed"),
        event_payload={
            "pipeline": _pipeline_context(callback),
            "analysis": analysis,
        },
    )
    return {
        "bound": True,
        "advanced": True,
        "workflow": updated,
    }


def _mark_pipeline_success(
    workflow: dict[str, Any],
    callback: YunxiaoPipelineFailureCallback,
) -> dict[str, Any]:
    context = _merge_context(workflow, {"pipeline": _pipeline_context(callback)})
    return db.update_workflow_pipeline_success(
        workflow_id=workflow["workflowId"],
        from_status=workflow["status"],
        pipeline_id=callback.pipeline_id,
        build_number=callback.build_number,
        branch_name=_clean_text(callback.branch_name),
        commit_id=_clean_text(callback.commit_id),
        context=context,
        operator=callback.operator,
        event_payload={"pipeline": _pipeline_context(callback)},
    )


def _workflow_id_from_payload(payload: dict[str, Any], callback: YunxiaoPipelineFailureCallback) -> str | None:
    return _clean_text(
        callback.workflow_id
        or _pick(_params_payload(payload), "WORKFLOW_ID", "workflowId", "workflow_id")
        or _pick(payload, "WORKFLOW_ID", "workflowId", "workflow_id")
    )


def _workflow_id_from_callback(callback: YunxiaoPipelineFailureCallback) -> str | None:
    return _clean_text(
        callback.workflow_id
        or _pick(callback.params, "WORKFLOW_ID", "workflowId", "workflow_id")
        or _pick(_params_payload(callback.params), "WORKFLOW_ID", "workflowId", "workflow_id")
    )


def _pipeline_context(callback: YunxiaoPipelineFailureCallback) -> dict[str, Any]:
    return {
        "taskId": callback.task_id,
        "pipelineId": callback.pipeline_id,
        "buildNumber": callback.build_number,
        "stageName": callback.stage_name,
        "branchName": callback.branch_name,
        "commitId": callback.commit_id,
        "operator": callback.operator,
    }


def _apifox_event_type(apifox: dict[str, Any]) -> str:
    if not apifox.get("enabled"):
        return "apifox_sync_skipped"
    return "apifox_sync_failed"


def _apifox_event_payload(apifox: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": apifox.get("enabled"),
        "imported": apifox.get("imported"),
        "reason": apifox.get("reason"),
        "pipelineId": apifox.get("pipelineId"),
        "projectName": apifox.get("projectName"),
        "projectNameSource": apifox.get("projectNameSource"),
        "projectId": apifox.get("projectId"),
        "projectConfigSource": apifox.get("projectConfigSource"),
    }


def _merge_context(workflow: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    context = dict(workflow.get("context") or {})
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(context.get(key), dict):
            context[key] = {**context[key], **value}
        else:
            context[key] = value
    return context


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def _params_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    global_params = payload.get("globalParams")
    if isinstance(global_params, list):
        for item in global_params:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if key:
                result[str(key)] = item.get("value")
    result.update(payload)
    return result


def _clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
