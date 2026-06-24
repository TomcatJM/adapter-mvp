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
    pass


def create_yunxiao_workitem(workflow: dict[str, Any], operator: str | None = None) -> dict[str, Any]:
    config = _load_config(workflow, purpose="create")
    payload = build_create_workitem_payload(workflow, config, operator)
    if config.get("authType") == "legacy_token":
        response = _request_yunxiao_legacy_openapi(payload=payload, config=config, timeout=config["timeout"])
    elif config.get("authType") == "personal_token":
        response = _request_yunxiao_personal_token_rest(
            method="POST",
            path=_personal_token_workitem_path(config),
            payload=_personal_token_workitem_payload(payload, config),
            config=config,
            timeout=config["timeout"],
        )
    else:
        organization_id = urllib.parse.quote(config["organizationId"], safe="")
        response = _request_yunxiao_openapi(
            method="POST",
            path=f"/organization/{organization_id}/workitem",
            action=CREATE_WORKITEM_ACTION,
            payload=payload,
            config=config,
            timeout=config["timeout"],
        )
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


def close_yunxiao_workitem(workflow: dict[str, Any], operator: str | None = None) -> dict[str, Any]:
    workitem_id = _clean_text(workflow.get("yunxiaoTaskId"))
    if not workitem_id:
        raise YunxiaoError(
            "Yunxiao task id missing: workflow.yunxiaoTaskId is required before closing. "
            "Solution: create or bind the Yunxiao workitem first."
        )

    config = _load_config(workflow, purpose="close")
    if config.get("authType") == "legacy_token":
        raise YunxiaoError(
            "Yunxiao close/writeback requires acs_ak OpenAPI auth. "
            "legacy_token only supports the compatibility create path and cannot close workitems. "
            f"Solution: configure adapter_yunxiao_account_config accountName={config.get('accountName') or ''} "
            "with auth_type=acs_ak, access_key_id, access_key_secret, and endpoint=devops.cn-hangzhou.aliyuncs.com."
        )
    current = get_yunxiao_workitem(workitem_id, config)
    if _is_workitem_closed(current, config):
        return {
            "workitemIdentifier": workitem_id,
            "workitemDisplayId": _extract_workitem_display_id(current),
            "alreadyClosed": True,
            "closedStatus": _extract_status_identifier(current),
            "closedStatusName": _extract_status_name(current),
            "writeback": "skipped",
            "configSource": config.get("configSource"),
            "authType": config.get("authType"),
        }

    _validate_close_target(config)
    comment = build_close_writeback_content(workflow, operator)
    comment_response = add_yunxiao_workitem_comment(workitem_id, comment, config)
    close_response = update_yunxiao_workitem_done_status(workitem_id, config)
    after = get_yunxiao_workitem(workitem_id, config)
    if _has_extractable_status(after) and not _is_workitem_closed(after, config):
        raise YunxiaoError(
            "Yunxiao workitem close verification failed: "
            f"workitem={workitem_id} currentStatus={_extract_status_identifier(after) or _extract_status_name(after) or 'unknown'} "
            f"expectedDoneStatus={config.get('doneStatusId') or config.get('closeTransitionId')}"
        )
    return {
        "workitemIdentifier": workitem_id,
        "workitemDisplayId": _extract_workitem_display_id(after),
        "alreadyClosed": False,
        "closedStatus": _extract_status_identifier(after) or config.get("doneStatusId"),
        "closedStatusName": _extract_status_name(after),
        "writeback": "success",
        "comment": _safe_response(comment_response),
        "close": _safe_response(close_response),
        "configSource": config.get("configSource"),
        "authType": config.get("authType"),
    }


def get_yunxiao_workitem(workitem_id: str, config: dict[str, Any]) -> Any:
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
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    if config.get("authType") == "personal_token":
        if not config.get("doneStatusId"):
            raise YunxiaoError(
                "Yunxiao personal_token close config missing: done_status_id. "
                "UpdateWorkitem with personal token closes by status id, not close_transition_id."
            )
        response = _request_yunxiao_personal_token_rest(
            method="PUT",
            path=_personal_token_workitem_path(config, urllib.parse.quote(workitem_id, safe="")),
            payload={"status": config["doneStatusId"]},
            config=config,
            timeout=config["timeout"],
        )
        _require_api_success(response, "Yunxiao close workitem")
        return response

    if config.get("closeTransitionId"):
        path = f"/organization/{organization_id}/workitems/update"
        payload = {
            "identifier": workitem_id,
            "transitionIdentifier": config["closeTransitionId"],
        }
        action = UPDATE_WORKITEM_ACTION
    else:
        field_type = config.get("doneStatusFieldId") or DEFAULT_DONE_STATUS_FIELD_ID
        path = f"/organization/{organization_id}/workitems/update"
        payload = {
            "identifier": workitem_id,
            "propertyKey": field_type,
            "propertyValue": config["doneStatusId"],
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
    _require_api_success(response, "Yunxiao close workitem")
    return response


def build_close_writeback_content(workflow: dict[str, Any], operator: str | None = None) -> str:
    context = workflow.get("context") or {}
    coding_result = context.get("codingResult") if isinstance(context.get("codingResult"), dict) else {}
    pipeline = context.get("pipeline") if isinstance(context.get("pipeline"), dict) else {}
    apifox = context.get("apifox") if isinstance(context.get("apifox"), dict) else {}
    apifox_result = apifox.get("lastResult") if isinstance(apifox.get("lastResult"), dict) else apifox
    workitem_display_id = _workflow_workitem_display_id(workflow)
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
) -> dict[str, Any]:
    requirement = (workflow.get("context") or {}).get("requirement") or {}
    title = _clean_text(requirement.get("summary")) or _clean_text(workflow.get("requirementKey"))
    if not title:
        raise YunxiaoError("Workflow requirement summary is required before creating Yunxiao workitem")

    payload: dict[str, Any] = {
        "subject": _clip(_sanitize(title), 256),
        "description": _build_description(workflow, requirement, operator),
        "assignedTo": config["assignee"],
        "spaceIdentifier": config["projectId"],
        "category": config["category"],
        "workitemTypeIdentifier": config["workitemTypeIdentifier"],
    }

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
    sprint_id = _clean_text(config.get("sprintId"))
    if sprint_id:
        payload["sprint"] = sprint_id
    return payload


def _request_yunxiao_openapi(
    *,
    method: str,
    path: str,
    action: str,
    payload: dict[str, Any] | None,
    config: dict[str, Any],
    timeout: int,
) -> Any:
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
    personal_payload: dict[str, Any] = {
        "spaceId": config["projectId"],
        "category": config["category"],
        "workitemTypeId": config["workitemTypeIdentifier"],
        "subject": payload["subject"],
        "description": payload["description"],
        "assignedTo": payload["assignedTo"],
    }
    if payload.get("fieldValueList"):
        personal_payload["fieldValueList"] = payload["fieldValueList"]
    for key in ("participants", "trackers", "verifier", "sprint"):
        if payload.get(key):
            personal_payload[key] = payload[key]
    return personal_payload


def _personal_token_workitem_path(config: dict[str, Any], workitem_id: str | None = None, suffix: str = "") -> str:
    organization_id = urllib.parse.quote(config["organizationId"], safe="")
    path = f"/oapi/v1/projex/organizations/{organization_id}/workitems"
    if workitem_id:
        path += f"/{workitem_id}"
    if suffix:
        path += suffix
    return path


def _load_config(workflow: dict[str, Any], *, purpose: str = "create") -> dict[str, Any]:
    project_name = _resolve_project_name(workflow)
    db_config = _load_db_config(project_name, workflow, purpose=purpose)
    if db_config:
        return db_config
    return _load_env_config(project_name, purpose=purpose)


def _load_db_config(project_name: str | None, workflow: dict[str, Any], *, purpose: str) -> dict[str, Any] | None:
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
    missing = [name for name, value in required.items() if not value]
    if missing:
        hint = "Yunxiao OpenAPI uses Alibaba Cloud AK auth; YUNXIAO_TOKEN is not enough for this path"
        if config.get("authType") == "legacy_token":
            hint = "Yunxiao legacy token auth is enabled for this account; configure legacy_token or switch auth_type to acs_ak"
        elif config.get("authType") == "personal_token":
            hint = "Yunxiao personal token auth is enabled; configure legacy_token with a Yunxiao personal access token"
        raise YunxiaoError(f"Yunxiao config missing: {', '.join(missing)}. {hint}")


def _db_required(config: dict[str, Any], purpose: str) -> dict[str, Any]:
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


def _validate_close_target(config: dict[str, Any]) -> None:
    if config.get("doneStatusId") or config.get("closeTransitionId"):
        return
    raise YunxiaoError(
        "Yunxiao close config missing: done_status_id or close_transition_id. "
        "Solution: configure adapter_yunxiao_project_config.done_status_id "
        "or YUNXIAO_DONE_STATUS_ID after confirming the target done status in Yunxiao."
    )


def _resolve_project_name(workflow: dict[str, Any]) -> str | None:
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


def _normalize_auth_type(value: Any) -> str:
    normalized = str(value or "acs_ak").strip().lower()
    if normalized in {"legacy", "token", "yunxiao_token"}:
        return "legacy_token"
    if normalized in {"personal", "personal_access_token", "pat"}:
        return "personal_token"
    if normalized not in {"acs_ak", "legacy_token", "personal_token"}:
        raise YunxiaoError(f"Unsupported Yunxiao auth_type: {normalized}")
    return normalized


def _default_endpoint(auth_type: str) -> str:
    if auth_type == "personal_token":
        return PERSONAL_TOKEN_ENDPOINT
    return DEFAULT_ENDPOINT


def _signed_headers(config: dict[str, Any], action: str, content_hash: str) -> dict[str, str]:
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


def _format_list(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- 未提供"
    return "\n".join(f"- {_clip(_sanitize(str(item)), 500)}" for item in value if item not in (None, ""))


def _format_api_changes(value: Any) -> str:
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
    try:
        detail = get_yunxiao_workitem(workitem_id, config)
    except YunxiaoError:
        return None
    return _extract_workitem_display_id(detail)


def _extract_workitem_display_id(response: Any) -> str | None:
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
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]{1,15}-\d{1,10}", value.strip()))


def _extract_status_identifier(response: Any) -> str | None:
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
    return bool(_extract_status_identifier(response) or _extract_status_name(response))


def _is_workitem_closed(response: Any, config: dict[str, Any]) -> bool:
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
    if _api_success(response):
        return
    raise YunxiaoError(f"{action} failed: {_response_error(response)}")


def _api_success(response: Any) -> bool:
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
    for source in _dict_candidates(response):
        code = source.get("errorCode") or source.get("code") or source.get("error")
        message = source.get("errorMessage") or source.get("message") or source.get("msg")
        if code or message:
            return _clip(_sanitize(f"code={code or ''} message={message or ''}"), 1000)
    return _clip(_sanitize(str(response)), 1000)


def _safe_response(response: Any) -> Any:
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
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:1000]


def _parse_error_detail(text: str) -> str:
    parsed = _parse_json(text)
    if isinstance(parsed, dict):
        return _response_error(parsed)
    return _clip(_sanitize(str(parsed)), 1000)


def _normalize_endpoint(value: str) -> tuple[str, str]:
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
    if value == "host":
        return "Host"
    return value


def _normalize_header_value(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _is_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _dict_candidates(payload: Any):
    if not isinstance(payload, dict):
        return
    yield payload
    for key in ("data", "result", "body", "workitemIdentifier", "identifier", "workitemId", "id"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            yield nested


def _pick(payload: Any, *keys: str, default: Any = None) -> Any:
    for source in _dict_candidates(payload):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return default


def _first_present(payload: Any, *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = _clean_text(payload.get(key))
        if value:
            return value
    return None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _parse_timeout(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise YunxiaoError("YUNXIAO_OPENAPI_TIMEOUT must be an integer") from exc


def _looks_secret_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return any(keyword.replace("_", "") in normalized for keyword in SECRET_KEYWORDS)


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return str(value or "")


def _first_item(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
    return _clean_text(value)


def _repo_name(value: Any) -> str | None:
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
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _sanitize(text: str) -> str:
    return SECRET_RE.sub(r"\1\2***", str(text or ""))


def _clip(text: str, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit]
