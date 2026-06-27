from __future__ import annotations

import re
import urllib.parse
from typing import Any

from app import db
from app.apifox import maybe_import_from_flow_event
from app.models import YunxiaoPipelineFailureCallback
from app.yunxiao_flow import discover_project_from_pipeline


PIPELINE_SUCCESS_FROM_STATUSES = {"CODING_REQUESTED", "CODE_SUBMITTED", "PIPELINE_RUNNING"}
PIPELINE_FAILURE_FROM_STATUSES = {"CODING_REQUESTED", "CODE_SUBMITTED", "PIPELINE_RUNNING", "PIPELINE_SUCCESS"}
PIPELINE_RUNNING_FROM_STATUSES = {"CODING_REQUESTED", "CODE_SUBMITTED"}
PIPELINE_SUCCESS_BINDING_STATUSES = {*PIPELINE_SUCCESS_FROM_STATUSES, "PIPELINE_SUCCESS"}
PIPELINE_RUNNING_BINDING_STATUSES = {*PIPELINE_RUNNING_FROM_STATUSES}
PIPELINE_FAILURE_BINDING_STATUSES = {*PIPELINE_FAILURE_FROM_STATUSES}
PROJECT_BINDING_LIMIT = 50
IDENTIFIER_RE = r"([A-Za-z0-9][A-Za-z0-9_.:-]{1,127})"
YUNXIAO_TASK_ALIASES = (
    "YUNXIAO_TASK_ID",
    "YUNXIAO_TASK_DISPLAY_ID",
    "YUNXIAO_DISPLAY_ID",
    "YUNXIAO_WORKITEM_ID",
    "YUNXIAO_WORKITEM_DISPLAY_ID",
    "WORKITEM_ID",
    "WORKITEM_DISPLAY_ID",
    "REQUIREMENT_ID",
    "TASK_ID",
)
YUNXIAO_TASK_COMMIT_ALIASES = (
    *YUNXIAO_TASK_ALIASES,
    "yunxiaoTaskId",
    "yunxiaoTaskDisplayId",
    "yunxiao_task_id",
    "yunxiao_task_display_id",
)
YUNXIAO_CLOSE_TASK_COMMIT_ALIASES = tuple(
    alias for alias in YUNXIAO_TASK_COMMIT_ALIASES if alias != "REQUIREMENT_ID"
)
YUNXIAO_TASK_PARAM_ALIASES = (
    *(alias for alias in YUNXIAO_TASK_COMMIT_ALIASES if alias != "TASK_ID"),
    "requirementId",
    "requirement_id",
    "workitemId",
    "workitemDisplayId",
    "workitem_id",
    "workitem_display_id",
)
YUNXIAO_TASK_CHINESE_ALIASES = (
    "云效任务ID",
    "云效任务编号",
    "云效任务展示ID",
    "云效任务显示ID",
    "云效任务页面ID",
    "云效展示ID",
    "云效页面ID",
    "云效显示ID",
    "云效工作项ID",
    "云效工作项展示ID",
    "云效工作项显示ID",
    "云效工作项页面ID",
    "任务编号",
)
YUNXIAO_TASK_COMMIT_ALIAS_RE = "|".join(re.escape(alias) for alias in YUNXIAO_TASK_COMMIT_ALIASES)
YUNXIAO_CLOSE_TASK_COMMIT_ALIAS_RE = "|".join(re.escape(alias) for alias in YUNXIAO_CLOSE_TASK_COMMIT_ALIASES)
YUNXIAO_TASK_CHINESE_ALIAS_RE = "|".join(re.escape(alias) for alias in YUNXIAO_TASK_CHINESE_ALIASES)
YUNXIAO_TASK_CHINESE_KEY_RE = (
    r"云效\s*(?:(?:任务|工作项|需求)\s*(?:展示|页面|显示)?\s*(?:ID|Id|id|编号)?|"
    r"(?:展示|页面|显示)\s*(?:ID|Id|id|编号)?|(?:ID|Id|id|编号))"
)
YUNXIAO_CLOSE_TASK_CHINESE_KEY_RE = (
    r"云效\s*(?:(?:任务|工作项)\s*(?:展示|页面|显示)?\s*(?:ID|Id|id|编号)?|"
    r"(?:ID|Id|id|编号))"
)
COMMIT_WORKFLOW_PATTERNS = (
    re.compile(rf"(?im)^\s*(?:WORKFLOW_ID|WORKFLOWID|workflowId|workflow_id)\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?m)^\s*(?:工作流ID|工作流编号)\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:WORKFLOW_ID|WORKFLOWID|workflowId|workflow_id)\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?:^|[\s,;，；])(?:工作流ID|工作流编号)\s*[:=：]\s*{IDENTIFIER_RE}\b"),
)
COMMIT_YUNXIAO_TASK_PATTERNS = (
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_TASK_CHINESE_KEY_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?m)^\s*(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_TASK_CHINESE_KEY_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
    re.compile(rf"(?:^|[\s,;，；])(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*{IDENTIFIER_RE}\b"),
)
COMMIT_YUNXIAO_TASK_VALUE_PATTERNS = (
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_TASK_CHINESE_KEY_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?m)^\s*(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_TASK_CHINESE_KEY_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?:^|[\s,;，；])(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
)
COMMIT_YUNXIAO_CLOSE_TASK_VALUE_PATTERNS = (
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_CLOSE_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?im)^\s*(?:{YUNXIAO_CLOSE_TASK_CHINESE_KEY_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?m)^\s*(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_CLOSE_TASK_COMMIT_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?i)(?:^|[\s,;，；])(?:{YUNXIAO_CLOSE_TASK_CHINESE_KEY_RE})\s*[:=：]\s*([^\r\n]+)"),
    re.compile(rf"(?:^|[\s,;，；])(?:{YUNXIAO_TASK_CHINESE_ALIAS_RE})\s*[:=：]\s*([^\r\n]+)"),
)
YUNXIAO_REFERENCE_KEYS = {
    "yunxiaoTaskId",
    "yunxiaoTaskDisplayId",
    "workitemIdentifier",
    "workitemDisplayId",
    "serialNumber",
    "serialNo",
    "taskIdentifiers",
    "taskIds",
    "taskDisplayIds",
    "demandIdentifiers",
    "demandDisplayIds",
}


def handle_pipeline_success(payload: dict[str, Any], callback: YunxiaoPipelineFailureCallback) -> dict[str, Any]:
    """handle流水线success。"""
    workflow, binding = _find_workflow_for_callback(payload, callback, PIPELINE_SUCCESS_BINDING_STATUSES)
    if not workflow:
        if binding.get("reason") in {"workflow not found", "workflow match ambiguous"}:
            return {
                "workflow": {
                    "bound": False,
                    "workflowId": binding.get("workflowId"),
                    "bindingSource": binding.get("source"),
                    "reason": binding.get("reason"),
                    "bindingAttempts": binding.get("attempts", []),
                },
                "apifox": {"enabled": False, "imported": False, "reason": binding.get("reason")},
            }
        apifox = maybe_import_from_flow_event(payload)
        return {
            "workflow": {
                "bound": False,
                "reason": "workflow not matched",
                "bindingAttempts": binding.get("attempts", []),
            },
            "apifox": apifox,
        }

    status = workflow["status"]
    if status == "APIFOX_SYNCED":
        context = _merge_context(workflow, {"pipeline": _pipeline_context(callback)})
        workflow = db.record_workflow_context_event(
            workflow_id=workflow["workflowId"],
            status="APIFOX_SYNCED",
            context=context,
            operator=callback.operator,
            event_type="pipeline_success_context_refreshed",
            message="Pipeline success context refreshed",
            event_payload={"pipeline": _pipeline_context(callback)},
        )
        return {
            "workflow": {
                "bound": True,
                "advanced": False,
                "workflow": workflow,
                "bindingSource": binding.get("source"),
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
                "bindingSource": binding.get("source"),
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
                "bindingSource": binding.get("source"),
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
            "bindingSource": binding.get("source"),
        },
        "apifox": apifox,
    }


def handle_pipeline_running(callback: YunxiaoPipelineFailureCallback) -> dict[str, Any]:
    """handle流水线running。"""
    workflow, binding = _find_workflow_for_callback(callback.params, callback, PIPELINE_RUNNING_BINDING_STATUSES)
    if not workflow:
        return {
            "bound": False,
            "reason": binding.get("reason") or "workflow not matched",
            "workflowId": binding.get("workflowId"),
            "bindingSource": binding.get("source"),
            "bindingAttempts": binding.get("attempts", []),
        }

    status = workflow["status"]
    if status == "PIPELINE_RUNNING":
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "bindingSource": binding.get("source"),
            "reason": "workflow already PIPELINE_RUNNING",
        }
    if status not in PIPELINE_RUNNING_FROM_STATUSES:
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "bindingSource": binding.get("source"),
            "reason": f"workflow status cannot accept pipeline running: {status}",
        }

    context = _merge_context(workflow, {"pipeline": _pipeline_context(callback)})
    updated = db.update_workflow_pipeline_running(
        workflow_id=workflow["workflowId"],
        pipeline_id=callback.pipeline_id,
        build_number=callback.build_number,
        branch_name=_clean_text(callback.branch_name),
        commit_id=_clean_text(callback.commit_id),
        context=context,
        operator=callback.operator,
        event_payload={"pipeline": _pipeline_context(callback)},
    )
    return {
        "bound": True,
        "advanced": True,
        "workflow": updated,
        "bindingSource": binding.get("source"),
    }


def handle_pipeline_failure(callback: YunxiaoPipelineFailureCallback, analysis: dict[str, Any]) -> dict[str, Any]:
    """handle流水线失败。"""
    workflow, binding = _find_workflow_for_callback(callback.params, callback, PIPELINE_FAILURE_BINDING_STATUSES)
    if not workflow:
        return {
            "bound": False,
            "reason": binding.get("reason") or "workflow not matched",
            "workflowId": binding.get("workflowId"),
            "bindingSource": binding.get("source"),
            "bindingAttempts": binding.get("attempts", []),
        }

    status = workflow["status"]
    if status == "PIPELINE_FAILED":
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "bindingSource": binding.get("source"),
            "reason": "workflow already PIPELINE_FAILED",
        }
    if status not in PIPELINE_FAILURE_FROM_STATUSES:
        return {
            "bound": True,
            "advanced": False,
            "workflow": workflow,
            "bindingSource": binding.get("source"),
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
        "bindingSource": binding.get("source"),
    }


def _mark_pipeline_success(
    workflow: dict[str, Any],
    callback: YunxiaoPipelineFailureCallback,
) -> dict[str, Any]:
    """内部辅助函数：标记流水线success。"""
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
    """内部辅助函数：工作流ID来自载荷。"""
    return _clean_text(
        callback.workflow_id
        or _pick(_params_payload(payload), "WORKFLOW_ID", "workflowId", "workflow_id")
        or _pick(payload, "WORKFLOW_ID", "workflowId", "workflow_id")
    )


def _workflow_id_from_callback(callback: YunxiaoPipelineFailureCallback) -> str | None:
    """内部辅助函数：工作流ID来自回调。"""
    return _clean_text(
        callback.workflow_id
        or _pick(callback.params, "WORKFLOW_ID", "workflowId", "workflow_id")
        or _pick(_params_payload(callback.params), "WORKFLOW_ID", "workflowId", "workflow_id")
    )


def _find_workflow_for_callback(
    payload: dict[str, Any],
    callback: YunxiaoPipelineFailureCallback,
    project_binding_statuses: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """内部辅助函数：查找工作流for回调。"""
    workflow_id = _workflow_id_from_payload(payload, callback)
    if workflow_id:
        workflow = db.find_workflow_instance(workflow_id)
        return workflow, {
            "source": "workflow_id",
            "workflowId": workflow_id,
            "reason": None if workflow else "workflow not found",
        }

    params = _params_payload(payload)
    attempts: list[dict[str, Any]] = []
    commit_binding = _binding_ids_from_commit_message(callback.commit_message)

    yunxiao_task_id = _pick_yunxiao_reference(params)
    if yunxiao_task_id:
        attempts.append({"source": "yunxiao_task_id", "value": yunxiao_task_id})
        workflow = _find_with_ambiguity_guard(
            lambda: _find_workflow_by_yunxiao_reference(yunxiao_task_id, project_binding_statuses),
            "yunxiao_task_id",
            attempts,
        )
        if isinstance(workflow, dict) and workflow.get("reason") == "workflow match ambiguous":
            return None, workflow
        if workflow:
            return workflow, {"source": "yunxiao_task_id", "attempts": attempts}

    commit_workflow_id = commit_binding.get("workflowId")
    if commit_workflow_id:
        attempts.append({"source": "commit_message_workflow_id", "workflowId": commit_workflow_id})
        workflow = db.find_workflow_instance(commit_workflow_id)
        return workflow, {
            "source": "commit_message_workflow_id",
            "workflowId": commit_workflow_id,
            "attempts": attempts,
            "reason": None if workflow else "workflow not found",
        }

    commit_yunxiao_task_ids = commit_binding.get("yunxiaoTaskIds") or []
    if commit_yunxiao_task_ids:
        for commit_yunxiao_task_id in commit_yunxiao_task_ids:
            attempts.append({"source": "commit_message_yunxiao_task_id", "value": commit_yunxiao_task_id})
            workflow = _find_with_ambiguity_guard(
                lambda value=commit_yunxiao_task_id: _find_workflow_by_yunxiao_reference(
                    value,
                    project_binding_statuses,
                ),
                "commit_message_yunxiao_task_id",
                attempts,
            )
            if isinstance(workflow, dict) and workflow.get("reason") == "workflow match ambiguous":
                return None, workflow
            if workflow:
                return workflow, {"source": "commit_message_yunxiao_task_id", "attempts": attempts}
        return None, {
            "source": "commit_message_yunxiao_task_id",
            "attempts": attempts,
            "reason": "workflow not found",
        }

    pipeline_id = _clean_text(callback.pipeline_id)
    build_number = _clean_text(callback.build_number)
    if pipeline_id and build_number:
        attempts.append({"source": "pipeline_build", "pipelineId": pipeline_id, "buildNumber": build_number})
        workflow = _find_with_ambiguity_guard(
            lambda: db.find_workflow_by_pipeline_build(pipeline_id, build_number),
            "pipeline_build",
            attempts,
        )
        if isinstance(workflow, dict) and workflow.get("reason") == "workflow match ambiguous":
            return None, workflow
        if workflow:
            return workflow, {"source": "pipeline_build", "attempts": attempts}

    branch_name = _clean_text(callback.branch_name)
    commit_id = _clean_text(callback.commit_id)
    if branch_name and commit_id:
        attempts.append({"source": "branch_commit", "branchName": branch_name, "commitId": commit_id})
        workflow = _find_with_ambiguity_guard(
            lambda: db.find_workflow_by_branch_commit(branch_name, commit_id),
            "branch_commit",
            attempts,
        )
        if isinstance(workflow, dict) and workflow.get("reason") == "workflow match ambiguous":
            return None, workflow
        if workflow:
            return workflow, {"source": "branch_commit", "attempts": attempts}

    if pipeline_id:
        project_name = _project_name_from_pipeline_config(pipeline_id)
        if project_name:
            attempts.append({"source": "project_active_workflow", "pipelineId": pipeline_id, "projectName": project_name})
            workflow = _find_with_ambiguity_guard(
                lambda: _find_active_workflow_by_project(project_name, project_binding_statuses),
                "project_active_workflow",
                attempts,
            )
            if isinstance(workflow, dict) and workflow.get("reason") == "workflow match ambiguous":
                return None, workflow
            if workflow:
                return workflow, {"source": "project_active_workflow", "attempts": attempts}

    return None, {"source": None, "attempts": attempts, "reason": "workflow not matched"}


def _find_with_ambiguity_guard(find: Any, source: str, attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """内部辅助函数：查找withambiguityguard。"""
    try:
        return find()
    except db.WorkflowLookupAmbiguousError as exc:
        return {
            "source": source,
            "attempts": attempts,
            "reason": "workflow match ambiguous",
            "error": str(exc),
        }


def _project_name_from_pipeline_config(pipeline_id: str) -> str | None:
    """内部辅助函数：项目name来自流水线配置。"""
    config = db.find_apifox_pipeline_config(pipeline_id)
    project_name = _clean_text((config or {}).get("projectName"))
    if project_name:
        return project_name
    discovery = discover_project_from_pipeline(pipeline_id)
    return _clean_text(discovery.get("projectName")) if discovery.get("matched") else None


def _find_workflow_by_yunxiao_reference(value: str, statuses: set[str]) -> dict[str, Any] | None:
    """内部辅助函数：查找工作流by云效reference。"""
    workflow = db.find_workflow_by_yunxiao_task_id(value)
    if workflow:
        return workflow
    return _find_workflow_by_yunxiao_display_id(value, statuses)


def _find_workflow_by_yunxiao_display_id(value: str, statuses: set[str]) -> dict[str, Any] | None:
    """内部辅助函数：查找工作流by云效展示ID。"""
    target = _normalize_identifier(value)
    if not target:
        return None
    candidates = [
        workflow
        for workflow in db.list_workflows_by_statuses(statuses, limit=PROJECT_BINDING_LIMIT)
        if target in {_normalize_identifier(item) for item in _workflow_yunxiao_reference_candidates(workflow)}
    ]
    if len(candidates) > 1:
        workflow_ids = ", ".join(str(item.get("workflowId")) for item in candidates[:5])
        raise db.WorkflowLookupAmbiguousError(
            f"Multiple active workflow instances matched Yunxiao display id={value}: {workflow_ids}"
        )
    return candidates[0] if candidates else None


def _workflow_yunxiao_reference_candidates(workflow: dict[str, Any]) -> list[str]:
    """内部辅助函数：工作流云效referencecandidates。"""
    context = workflow.get("context") if isinstance(workflow.get("context"), dict) else {}
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    values: list[Any] = [
        workflow.get("yunxiaoTaskId"),
        workflow.get("yunxiaoTaskDisplayId"),
    ]
    for source in (
        yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {},
        yunxiao.get("closeResult") if isinstance(yunxiao.get("closeResult"), dict) else {},
        context.get("codingRequest") if isinstance(context.get("codingRequest"), dict) else {},
    ):
        values.extend(_collect_yunxiao_reference_values(source))
    return _unique_texts(values)


def _find_active_workflow_by_project(project_name: str, statuses: set[str]) -> dict[str, Any] | None:
    """内部辅助函数：查找active工作流by项目。"""
    project_aliases = _project_aliases(project_name)
    candidates = [
        workflow
        for workflow in db.list_workflows_by_statuses(statuses, limit=PROJECT_BINDING_LIMIT)
        if _project_matches_workflow(project_aliases, workflow)
    ]
    if len(candidates) > 1:
        workflow_ids = ", ".join(str(item.get("workflowId")) for item in candidates[:5])
        raise db.WorkflowLookupAmbiguousError(
            f"Multiple active workflow instances matched projectName={project_name}: {workflow_ids}"
        )
    return candidates[0] if candidates else None


def _project_aliases(project_name: str) -> set[str]:
    """内部辅助函数：项目aliases。"""
    aliases = {_clean_text(project_name)}
    project_config = db.find_yunxiao_project_config(project_name)
    organization_id = _clean_text((project_config or {}).get("organizationId"))
    yunxiao_project_id = _clean_text((project_config or {}).get("projectId"))
    if organization_id and yunxiao_project_id:
        for config in db.list_yunxiao_project_configs():
            if _clean_text(config.get("organizationId")) == organization_id and _clean_text(config.get("projectId")) == yunxiao_project_id:
                aliases.add(_clean_text(config.get("projectName")))
    return {alias for alias in aliases if alias}


def _project_matches_workflow(project_aliases: set[str], workflow: dict[str, Any]) -> bool:
    """内部辅助函数：项目matches工作流。"""
    expected = {_normalize_project_name(alias) for alias in project_aliases}
    expected.discard(None)
    if not expected:
        return False
    return any(_normalize_project_name(value) in expected for value in _workflow_project_candidates(workflow))


def _workflow_project_candidates(workflow: dict[str, Any]) -> list[str]:
    """内部辅助函数：工作流项目candidates。"""
    context = workflow.get("context") or {}
    requirement = context.get("requirement") or {}
    requirement_extra = requirement.get("extra") if isinstance(requirement.get("extra"), dict) else {}
    values: list[Any] = []
    for source in (context, requirement, requirement_extra):
        values.extend(
            source.get(key)
            for key in (
                "projectName",
                "project_name",
                "sourceProjectName",
                "source_project_name",
                "documentProjectName",
                "document_project_name",
                "serviceName",
                "service_name",
                "appName",
                "app_name",
            )
        )
    values.append(_first_item(requirement.get("affectedRepos")))
    values.append(_repo_name(workflow.get("repoUrl") or requirement.get("repoUrl")))
    yunxiao = context.get("yunxiao") or {}
    if isinstance(yunxiao, dict):
        create_result = yunxiao.get("createResult") or {}
        if isinstance(create_result, dict):
            values.append(create_result.get("projectName"))
    return [text for text in (_clean_text(value) for value in values) if text]


def _normalize_project_name(value: Any) -> str | None:
    """内部辅助函数：归一化项目name。"""
    text = _clean_text(value)
    return text.lower() if text else None


def _normalize_identifier(value: Any) -> str | None:
    """内部辅助函数：归一化identifier。"""
    text = _clean_text(value)
    return text.upper() if text else None


def _first_item(value: Any) -> str | None:
    """内部辅助函数：第一个条目。"""
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
        return None
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


def _pipeline_context(callback: YunxiaoPipelineFailureCallback) -> dict[str, Any]:
    """内部辅助函数：流水线上下文。"""
    return {
        "taskId": callback.task_id,
        "pipelineId": callback.pipeline_id,
        "buildNumber": callback.build_number,
        "stageName": callback.stage_name,
        "branchName": callback.branch_name,
        "commitId": callback.commit_id,
        "commitMessage": callback.commit_message,
        "operator": callback.operator,
    }


def _binding_ids_from_commit_message(message: str | None) -> dict[str, Any]:
    """内部辅助函数：bindingids来自commit消息。"""
    text = _clean_text(message)
    if not text:
        return {}
    result: dict[str, str] = {}
    for pattern in COMMIT_WORKFLOW_PATTERNS:
        match = pattern.search(text)
        if match:
            result["workflowId"] = match.group(1)
            break
    yunxiao_task_ids = _yunxiao_task_ids_from_commit_message(text)
    if yunxiao_task_ids:
        result["yunxiaoTaskId"] = yunxiao_task_ids[0]
        result["yunxiaoTaskIds"] = yunxiao_task_ids
    return result


def _yunxiao_task_ids_from_commit_message(text: str) -> list[str]:
    """从提交信息中提取一个或多个云效任务引用。"""
    values: list[str] = []
    for pattern in COMMIT_YUNXIAO_TASK_VALUE_PATTERNS:
        for match in pattern.finditer(text):
            values.extend(_identifier_values(match.group(1)))
    if not values:
        for pattern in COMMIT_YUNXIAO_TASK_PATTERNS:
            values.extend(match.group(1) for match in pattern.finditer(text))
    return _unique_texts(values)


def yunxiao_close_task_ids_from_commit_message(text: str) -> list[str]:
    """从提交信息中提取显式允许关单的云效任务引用。"""
    values: list[str] = []
    for pattern in COMMIT_YUNXIAO_CLOSE_TASK_VALUE_PATTERNS:
        for match in pattern.finditer(text):
            values.extend(_identifier_values(match.group(1)))
    return _unique_texts(values)


def _identifier_values(value: Any) -> list[str]:
    """从逗号、顿号或空格分隔的文本中提取标识符。"""
    text = _clean_text(value)
    if not text:
        return []
    return [match.group(1) for match in re.finditer(IDENTIFIER_RE, text)]


def _collect_yunxiao_reference_values(value: Any) -> list[Any]:
    """递归收集云效需求树里的工作项内部 ID 和展示 ID。"""
    values: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in YUNXIAO_REFERENCE_KEYS:
                values.extend(item if isinstance(item, list) else [item])
            if isinstance(item, (dict, list)):
                values.extend(_collect_yunxiao_reference_values(item))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                values.extend(_collect_yunxiao_reference_values(item))
    return values


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


def _apifox_event_type(apifox: dict[str, Any]) -> str:
    """内部辅助函数：Apifox事件类型。"""
    if not apifox.get("enabled"):
        return "apifox_sync_skipped"
    return "apifox_sync_failed"


def _apifox_event_payload(apifox: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：Apifox事件载荷。"""
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
    """内部辅助函数：merge上下文。"""
    context = dict(workflow.get("context") or {})
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(context.get(key), dict):
            context[key] = {**context[key], **value}
        else:
            context[key] = value
    return context


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """pick。"""
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def _pick_yunxiao_reference(payload: dict[str, Any]) -> str | None:
    """内部辅助函数：pick云效reference。"""
    value = _pick(payload, *YUNXIAO_TASK_PARAM_ALIASES)
    if _clean_text(value):
        return _clean_text(value)

    for key, item_value in payload.items():
        if item_value in (None, ""):
            continue
        if _is_yunxiao_reference_key(key):
            return _clean_text(item_value)
    return None


def _is_yunxiao_reference_key(key: Any) -> bool:
    """内部辅助函数：is云效referencekey。"""
    text = _clean_text(key)
    if not text:
        return False
    if text in YUNXIAO_TASK_PARAM_ALIASES:
        return True

    compact = re.sub(r"[\s_\-]+", "", text)
    lower = compact.lower()
    known = {re.sub(r"[\s_\-]+", "", alias).lower() for alias in YUNXIAO_TASK_PARAM_ALIASES}
    if lower in known:
        return True
    if lower.startswith("yunxiao") and any(part in lower for part in ("id", "task", "workitem", "display", "requirement")):
        return True
    return bool(re.search(r"云效(?=.{0,16}(?:id|编号|任务|工作项|需求|展示|页面|显示))", compact, re.IGNORECASE))


def _params_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：params载荷。"""
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
    """内部辅助函数：清洗文本。"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
