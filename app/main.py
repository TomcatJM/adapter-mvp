import json
import urllib.parse
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import db
from app.apifox import (
    OpenapiSignatureError,
    OpenapiValidationError,
    fetch_sanitized_openapi,
    verify_signed_upstream_url,
)
from app.auth import require_api_token, require_execute_approval
from app.dingtalk_docs import DingTalkDocError, read_dingtalk_doc, resolve_dingtalk_operator
from app.audit import (
    find_by_task_id,
    log_apifox_import,
    log_execute,
    log_pipeline_failure,
    log_preview,
    log_status,
    log_webhook_error,
)
from app.models import (
    AdapterRequest,
    AdapterResult,
    AdapterStatus,
    WorkflowAdvanceRequest,
    WorkflowCodingResultRequest,
    WorkflowRequirementRequest,
    WorkflowResolveRequest,
    WorkflowRetryRequest,
    WorkflowStartRequest,
    YunxiaoPipelineFailureCallback,
    YunxiaoTaskCallback,
)
from app.pipeline_agent import analyze_pipeline_failure
from app.registry import registry
from app.status_store import status_store
from app.workflow import (
    WorkflowError,
    advance_workflow,
    get_workflow,
    resolve_workflow,
    retry_workflow,
    start_workflow,
    submit_coding_result,
    submit_requirement,
)
from app.yunxiao_pipeline import handle_pipeline_failure, handle_pipeline_running, handle_pipeline_success


OPENAPI_TAGS = [
    {"name": "健康检查", "description": "Adapter 服务健康状态"},
    {"name": "OpenAPI", "description": "OpenAPI 清洗与导出"},
    {"name": "钉钉文档", "description": "钉钉/Alidocs 文档读取与配置"},
    {"name": "交付工作流", "description": "需求交付 workflow 账本"},
    {"name": "适配器执行", "description": "Adapter 预览、执行、状态和审计"},
    {"name": "云效回调", "description": "云效任务和流水线事件回调"},
]

app = FastAPI(title="Adapter MVP", version="0.1.0", openapi_tags=OPENAPI_TAGS)

YUNXIAO_FLOW_EVENT_PATH = "/callbacks/yunxiao/flow-event"
YUNXIAO_FLOW_EVENT_PUBLIC_PATH = "/callbacks/yunxiao/flow-event/public"
YUNXIAO_RUNNING_STATUSES = {"RUNNING", "START", "STARTED", "IN_PROGRESS", "PROCESSING"}


class DingTalkDocReadRequest(BaseModel):
    url: str | None = Field(default=None, description="DingTalk/Alidocs URL")
    nodeId: str | None = Field(default=None, description="DingTalk/Alidocs node id")
    workbookId: str | None = Field(default=None, description="Explicit workbook id for axls docs")
    configName: str | None = Field(default=None, description="DingTalk app config name")
    kind: str | None = Field(default=None, description="Document kind: adoc or axls")
    sheetId: str | None = Field(default=None, description="Sheet id for axls docs")
    range: str = Field(default="A1:J50", description="Sheet range for axls docs")
    timeout: int = Field(default=60, ge=5, le=180)


class DingTalkDocConfigRequest(BaseModel):
    configName: str = Field(default="default", description="DingTalk document config name")
    appName: str | None = Field(default=None, description="Existing DingTalk app name")
    operatorId: str | None = Field(default=None, description="DingTalk userId used to read documents")
    docInfoMethod: str | None = None
    docInfoUrlTemplate: str | None = None
    docInfoBodyTemplate: dict[str, Any] | list[Any] | str | None = None
    docReadMethod: str | None = None
    docReadUrlTemplate: str | None = None
    docReadBodyTemplate: dict[str, Any] | list[Any] | str | None = None
    sheetListMethod: str | None = None
    sheetListUrlTemplate: str | None = None
    sheetListBodyTemplate: dict[str, Any] | list[Any] | str | None = None
    sheetRangeMethod: str | None = None
    sheetRangeUrlTemplate: str | None = None
    sheetRangeBodyTemplate: dict[str, Any] | list[Any] | str | None = None
    remark: str | None = None


class DingTalkResolveOperatorRequest(BaseModel):
    userId: str = Field(description="DingTalk contact userId to resolve")
    configName: str | None = Field(default=None, description="DingTalk document config name")
    timeout: int = Field(default=60, ge=5, le=180)
    updateConfig: bool = Field(default=False, description="Write resolved unionId back as operatorId")


@app.get("/health", summary="健康检查", tags=["健康检查"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/adapter/openapi/{project_name}", summary="获取清洗后的 OpenAPI", tags=["OpenAPI"])
def adapter_openapi(project_name: str, upstreamUrl: str | None = None, signature: str | None = None):
    try:
        upstream_url = verify_signed_upstream_url(project_name, upstreamUrl, signature)
        return fetch_sanitized_openapi(project_name, upstream_url=upstream_url)
    except OpenapiSignatureError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OpenapiValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/adapter/dingtalk/read", summary="读取钉钉文档", tags=["钉钉文档"], dependencies=[Depends(require_api_token)])
def adapter_dingtalk_read(request: DingTalkDocReadRequest):
    try:
        return read_dingtalk_doc(
            url=request.url,
            node_id=request.nodeId,
            sheet_id=request.sheetId,
            workbook_id=request.workbookId,
            cell_range=request.range,
            timeout=request.timeout,
            config_name=request.configName,
            kind=request.kind,
        )
    except DingTalkDocError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/adapter/dingtalk/config",
    summary="保存钉钉文档读取配置",
    tags=["钉钉文档"],
    dependencies=[Depends(require_api_token)],
)
def adapter_dingtalk_config(request: DingTalkDocConfigRequest):
    try:
        return {
            "ok": True,
            "config": db.upsert_dingtalk_doc_config(
                request.configName,
                _dingtalk_config_changes(request),
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/adapter/dingtalk/resolve-operator",
    summary="解析钉钉操作人",
    tags=["钉钉文档"],
    dependencies=[Depends(require_api_token)],
)
def adapter_dingtalk_resolve_operator(request: DingTalkResolveOperatorRequest):
    try:
        result = resolve_dingtalk_operator(
            user_id=request.userId,
            config_name=request.configName,
            timeout=request.timeout,
        )
        response: dict[str, Any] = {
            "ok": True,
            "configName": result["configName"],
            "appName": result.get("appName"),
            "userId": result["userId"],
            "unionId": result["unionId"],
        }
        if request.updateConfig:
            response["config"] = db.upsert_dingtalk_doc_config(
                result["configName"],
                {"operator_id": result["unionId"]},
            )
        return response
    except DingTalkDocError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/workflow/start", summary="创建交付工作流", tags=["交付工作流"], dependencies=[Depends(require_api_token)])
def workflow_start(request: WorkflowStartRequest):
    try:
        workflow = start_workflow(request)
        return {
            "workflowId": workflow["workflowId"],
            "status": workflow["status"],
            "workflow": workflow,
        }
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/workflow/{workflow_id}", summary="查询交付工作流", tags=["交付工作流"], dependencies=[Depends(require_api_token)])
def workflow_get(workflow_id: str, eventLimit: int = 50):
    try:
        return get_workflow(workflow_id, eventLimit)
    except WorkflowError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/workflow/{workflow_id}/advance",
    summary="推进交付工作流",
    tags=["交付工作流"],
    dependencies=[Depends(require_api_token)],
)
def workflow_advance(workflow_id: str, request: WorkflowAdvanceRequest):
    try:
        return advance_workflow(workflow_id, request)
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/workflow/{workflow_id}/requirement",
    summary="提交结构化需求",
    tags=["交付工作流"],
    dependencies=[Depends(require_api_token)],
)
def workflow_requirement(workflow_id: str, request: WorkflowRequirementRequest):
    try:
        return submit_requirement(workflow_id, request)
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/workflow/{workflow_id}/coding-result",
    summary="提交编码结果",
    tags=["交付工作流"],
    dependencies=[Depends(require_api_token)],
)
def workflow_coding_result(workflow_id: str, request: WorkflowCodingResultRequest):
    try:
        return submit_coding_result(workflow_id, request)
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/workflow/{workflow_id}/retry",
    summary="重试交付工作流",
    tags=["交付工作流"],
    dependencies=[Depends(require_api_token)],
)
def workflow_retry(workflow_id: str, request: WorkflowRetryRequest):
    try:
        return retry_workflow(workflow_id, request)
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/workflow/{workflow_id}/resolve",
    summary="恢复交付工作流",
    tags=["交付工作流"],
    dependencies=[Depends(require_api_token)],
)
def workflow_resolve(workflow_id: str, request: WorkflowResolveRequest):
    try:
        return resolve_workflow(workflow_id, request)
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/adapter/preview", summary="预览适配器操作", tags=["适配器执行"], dependencies=[Depends(require_api_token)])
def preview(request: AdapterRequest):
    try:
        adapter = registry.find(request.system, request.action)
        result = adapter.preview(request)
        log_preview(request, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/adapter/execute",
    summary="执行适配器操作",
    tags=["适配器执行"],
    response_model=AdapterResult,
    dependencies=[Depends(require_api_token)],
)
def execute(request: AdapterRequest):
    try:
        require_execute_approval(request.params)
        adapter = registry.find(request.system, request.action)
        result = adapter.execute(request)
        status_store.put(result)
        log_execute(request, result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/adapter/status/{task_id}",
    summary="查询任务状态",
    tags=["适配器执行"],
    response_model=AdapterStatus,
    dependencies=[Depends(require_api_token)],
)
def status(task_id: str):
    result = status_store.get(task_id)
    log_status(task_id, result)
    return result


@app.get("/adapter/audit/{task_id}", summary="查询任务审计", tags=["适配器执行"], dependencies=[Depends(require_api_token)])
def audit(task_id: str, limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    return {"taskId": task_id, "items": find_by_task_id(task_id, safe_limit)}


@app.post("/callbacks/yunxiao/task", summary="接收云效任务回调", tags=["云效回调"], dependencies=[Depends(require_api_token)])
def yunxiao_task_callback(callback: YunxiaoTaskCallback):
    params = {
        **callback.params,
        "hostId": callback.host_id,
    }
    if callback.approval_id:
        params["approvalId"] = callback.approval_id
    if callback.approved:
        params["approved"] = True

    request = AdapterRequest(
        taskId=callback.task_id,
        operator=callback.operator,
        system="ssh",
        action="check_connectivity",
        env=callback.env,
        params=params,
    )
    adapter = registry.find(request.system, request.action)
    if not callback.execute:
        result = adapter.preview(request)
        log_preview(request, result)
        return {
            "source": "yunxiao",
            "mode": "preview",
            "adapter": result,
        }

    require_execute_approval(request.params)
    result = adapter.execute(request)
    status_store.put(result)
    log_execute(request, result)
    return {
        "source": "yunxiao",
        "mode": "execute",
        "adapter": result,
    }


@app.post(
    "/callbacks/yunxiao/pipeline-failure",
    summary="接收云效流水线失败回调",
    tags=["云效回调"],
    dependencies=[Depends(require_api_token)],
)
def yunxiao_pipeline_failure_callback(callback: YunxiaoPipelineFailureCallback):
    analysis = analyze_pipeline_failure(callback.log_tail, callback.stage_name)
    log_pipeline_failure(callback, analysis)
    workflow = handle_pipeline_failure(callback, analysis)
    return {
        "source": "yunxiao",
        "mode": "pipeline_failure",
        "taskId": callback.task_id,
        "pipelineId": callback.pipeline_id,
        "buildNumber": callback.build_number,
        "stageName": callback.stage_name,
        "analysis": analysis,
        "workflow": workflow,
    }


@app.post(YUNXIAO_FLOW_EVENT_PATH, summary="接收云效流水线事件", tags=["云效回调"], dependencies=[Depends(require_api_token)])
def yunxiao_flow_event(payload: dict[str, Any]):
    return _handle_flow_event_safely(payload, source="yunxiao_flow_event")


@app.post(YUNXIAO_FLOW_EVENT_PUBLIC_PATH, summary="接收云效公开流水线事件", tags=["云效回调"])
def yunxiao_flow_event_public(payload: dict[str, Any]):
    return _handle_flow_event_safely(payload, source="yunxiao_flow_event_public")


def _handle_flow_event_safely(payload: dict[str, Any], source: str) -> dict[str, Any]:
    try:
        return _handle_flow_event(payload)
    except Exception as exc:
        log_webhook_error(source, payload, exc)
        return {
            "source": "yunxiao",
            "mode": "flow_event",
            "handled": False,
            "error": "internal_error",
            "message": f"{type(exc).__name__}: {str(exc)}"[:1024],
        }


def _handle_flow_event(payload: dict[str, Any]) -> dict[str, Any]:
    status_code = str(_pick(_task_payload(payload), "statusCode", "status_code", "status", default="")).upper()
    if status_code in YUNXIAO_RUNNING_STATUSES:
        callback = _normalize_flow_event(payload)
        workflow = handle_pipeline_running(callback)
        return {
            "source": "yunxiao",
            "mode": "flow_event",
            "statusCode": status_code,
            "taskId": callback.task_id,
            "pipelineId": callback.pipeline_id,
            "buildNumber": callback.build_number,
            "stageName": callback.stage_name,
            "workflow": workflow,
        }
    if status_code in {"SUCCESS", "FINISH"}:
        callback = _normalize_flow_event(payload)
        result = handle_pipeline_success(payload, callback)
        log_apifox_import(callback.task_id, callback.operator, result["apifox"])
        return {
            "source": "yunxiao",
            "mode": "flow_event",
            "statusCode": status_code,
            "taskId": callback.task_id,
            "pipelineId": callback.pipeline_id,
            "buildNumber": callback.build_number,
            "stageName": callback.stage_name,
            "workflow": result["workflow"],
            "apifox": result["apifox"],
        }
    if status_code not in {"FAIL", "FAILED", "ERROR", "CANCELED", "CANCELLED", "CANCELLING", "UNKNOWN", "UNKOWN"}:
        return {
            "source": "yunxiao",
            "mode": "flow_event",
            "ignored": True,
            "statusCode": status_code,
            "reason": "non-failure status",
        }

    callback = _normalize_flow_event(payload)
    analysis = analyze_pipeline_failure(callback.log_tail, callback.stage_name)
    log_pipeline_failure(callback, analysis)
    workflow = handle_pipeline_failure(callback, analysis)
    return {
        "source": "yunxiao",
        "mode": "flow_event",
        "taskId": callback.task_id,
        "pipelineId": callback.pipeline_id,
        "buildNumber": callback.build_number,
        "stageName": callback.stage_name,
        "analysis": analysis,
        "workflow": workflow,
    }


def _normalize_flow_event(payload: dict[str, Any]) -> YunxiaoPipelineFailureCallback:
    task = _task_payload(payload)
    params = _params_payload(payload)
    source = _source_payload(payload)
    pipeline_id = _pick(task, "pipelineId", "pipeline_id", "pipelineID", "flowId", "flow_id", default="unknown")
    build_number = _pick(task, "buildNumber", "build_number", "buildNo", "build_no", "runId", "run_id", default="0")
    requirement_id = _pick(params, "REQUIREMENT_ID", "requirementId", "requirement_id", "workitemId", "workitem_id", "taskId", "task_id")
    workflow_id = _pick(params, "WORKFLOW_ID", "workflowId", "workflow_id")
    task_id = _pick(params, "TASK_ID", "taskId", "task_id")
    if not task_id and requirement_id:
        task_id = f"rel-{requirement_id}-{build_number}"
    if not task_id:
        task_id = f"yx-flow-{pipeline_id}-{build_number}"
    return YunxiaoPipelineFailureCallback(
        taskId=task_id,
        workflowId=workflow_id,
        pipelineId=str(pipeline_id),
        buildNumber=str(build_number),
        stageName=str(_pick(task, "stageName", "stage_name", default="yunxiao-flow-event"))
        + "/"
        + str(_pick(task, "taskName", "task_name", default="unknown-task")),
        branchName=(
            _pick(source, "branchName", "branch_name", "branch")
            or _pick(task, "branchName", "branch_name", "branch")
            or _pick(params, "BRANCH_NAME", "branchName", "branch_name", "branch")
        ),
        commitId=(
            _pick(source, "commitId", "commit_id", "commit")
            or _pick(task, "commitId", "commit_id", "commit")
            or _pick(params, "COMMIT_ID", "commitId", "commit_id", "commit")
        ),
        commitMessage=_decode_commit_message(
            _pick(source, "commitMessage", "commit_message", "commitMsg", "commit_msg")
            or _pick(task, "commitMessage", "commit_message", "commitMsg", "commit_msg")
            or _pick(
                params,
                "COMMIT_MESSAGE",
                "commitMessage",
                "commit_message",
                "COMMIT_MSG",
                "commitMsg",
                "commit_msg",
                "CI_COMMIT_MESSAGE",
                "CI_COMMIT_TITLE",
                "CI_COMMIT_TITLE_1",
            )
        ),
        operator=str(_pick(params, "BUILD_USER", "operator", "triggerUser", "trigger_user", "buildUser", "build_user", default="yunxiao")),
        exitCode=1,
        logTail=str(_pick(task, "message", "statusName", "status_name", default="")),
        logUrl=_pick(task, "pipelineUrl", "pipeline_url", "logUrl", "log_url", "url", "detailUrl", "detail_url"),
        params=payload,
    )


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def _dingtalk_config_changes(request: DingTalkDocConfigRequest) -> dict[str, Any]:
    field_map = {
        "appName": "app_name",
        "operatorId": "operator_id",
        "docInfoMethod": "doc_info_method",
        "docInfoUrlTemplate": "doc_info_url_template",
        "docInfoBodyTemplate": "doc_info_body_template",
        "docReadMethod": "doc_read_method",
        "docReadUrlTemplate": "doc_read_url_template",
        "docReadBodyTemplate": "doc_read_body_template",
        "sheetListMethod": "sheet_list_method",
        "sheetListUrlTemplate": "sheet_list_url_template",
        "sheetListBodyTemplate": "sheet_list_body_template",
        "sheetRangeMethod": "sheet_range_method",
        "sheetRangeUrlTemplate": "sheet_range_url_template",
        "sheetRangeBodyTemplate": "sheet_range_body_template",
        "remark": "remark",
    }
    supplied = request.model_fields_set
    return {
        target: getattr(request, source)
        for source, target in field_map.items()
        if source in supplied
    }


def _task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task")
    return task if isinstance(task, dict) else payload


def _source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        source = sources[0]
        data = source.get("data")
        if isinstance(data, dict):
            return {**source, **data}
        return source
    return payload


def _decode_commit_message(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed: Any | None = value if isinstance(value, (dict, list)) else None
    decoded: str | None = None
    if parsed is None:
        text = str(value).strip()
        if not text:
            return None
        decoded = urllib.parse.unquote(text)
        for candidate in (text, decoded):
            try:
                parsed = json.loads(candidate)
                break
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if parsed is None:
            return decoded

    if isinstance(parsed, str):
        return _decode_commit_text(parsed)
    messages: list[str] = []
    items = parsed if isinstance(parsed, list) else [parsed]
    for item in items:
        if not isinstance(item, dict):
            continue
        message = _pick(item, "commitMsg", "commitMessage", "commit_message", "message")
        if message in (None, ""):
            continue
        decoded_message = _decode_commit_text(message)
        if decoded_message:
            messages.append(decoded_message)
    if messages:
        return "\n\n".join(message for message in messages if message)
    return decoded


def _decode_commit_text(value: Any) -> str | None:
    text = urllib.parse.unquote(str(value).strip())
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return text or None


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
