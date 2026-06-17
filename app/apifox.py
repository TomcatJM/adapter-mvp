from __future__ import annotations

import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from app import db


class OpenapiValidationError(ValueError):
    pass


def maybe_import_from_flow_event(payload: dict[str, Any]) -> dict[str, Any]:
    config = _resolve_config(payload)
    safe_config = _safe_config(config)
    if not config["autoImport"]:
        return {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true", **safe_config}
    if config["projectNameSource"] == "default":
        return {
            "enabled": True,
            "imported": False,
            "reason": f"missing project mapping for pipelineId={config['pipelineId']}",
            **safe_config,
        }
    missing = [key for key in ("accessToken", "projectId", "openapiUrl") if not config.get(key)]
    if missing:
        return {"enabled": True, "imported": False, "reason": f"missing {','.join(missing)}", **safe_config}
    if config["stripProjectPath"]:
        preflight = _preflight_openapi(config["projectName"])
        if not preflight["ok"]:
            return {
                "enabled": True,
                "imported": False,
                "reason": f"OpenAPI preflight failed: {preflight['error']}",
                **safe_config,
                "apifoxResult": preflight,
            }
    result = _import_openapi(config)
    imported = isinstance(result.get("statusCode"), int) and 200 <= result["statusCode"] < 300
    reason = "Apifox import finished" if imported else f"Apifox import failed: {result.get('statusCode')}"
    return {"enabled": True, "imported": imported, "reason": reason, **safe_config, "apifoxResult": result}


def _resolve_config(payload: dict[str, Any]) -> dict[str, Any]:
    params = _params_payload(payload)
    task = _task_payload(payload)
    source = _source_payload(payload)
    pipeline_id = str(_pick(task, "pipelineId", "pipeline_id", "pipelineID", "flowId", "flow_id", default=""))
    pipeline_config = _find_pipeline_config(pipeline_id)
    payload_project_name = _pick(params, "PROJECT_NAME", "SERVICE_NAME", "APP_NAME", "APIFOX_PROJECT_KEY")
    env_project_name = os.getenv(f"APIFOX_PIPELINE_{_normalize_key(pipeline_id)}_PROJECT")
    repo_project_name = _repo_name(str(_pick(source, "repo", default="")))
    if payload_project_name:
        project_name = str(payload_project_name)
        project_name_source = "payload"
        project_name_remark = None
    elif pipeline_config and pipeline_config.get("projectName"):
        project_name = str(pipeline_config["projectName"])
        project_name_source = "database_pipeline"
        project_name_remark = pipeline_config.get("remark")
    elif env_project_name:
        project_name = str(env_project_name)
        project_name_source = "environment_pipeline"
        project_name_remark = None
    elif repo_project_name:
        project_name = str(repo_project_name)
        project_name_source = "repo"
        project_name_remark = None
    else:
        project_name = "default"
        project_name_source = "default"
        project_name_remark = None
    project_key = _normalize_key(project_name)
    project_config = _find_project_config(project_name)
    project_id = (
        _pick(params, "APIFOX_PROJECT_ID")
        or (project_config or {}).get("apifoxProjectId")
        or os.getenv(f"APIFOX_PROJECT_{project_key}_ID")
        or (os.getenv("APIFOX_DEFAULT_PROJECT_ID") if project_name_source == "default" else None)
        or (os.getenv("APIFOX_PROJECT_ID") if project_name_source == "default" else None)
    )
    upstream_openapi_url = (
        _pick(params, "OPENAPI_URL", "APIFOX_OPENAPI_URL")
        or os.getenv(f"OPENAPI_{project_key}_URL")
        or os.getenv("OPENAPI_URL")
        or _openapi_url_from_template(project_name, project_key)
    )
    strip_project_path = os.getenv("APIFOX_STRIP_PROJECT_PATH", "true").lower() == "true"
    openapi_url = _adapter_openapi_url(project_name) if strip_project_path else upstream_openapi_url
    return {
        "autoImport": os.getenv("APIFOX_AUTO_IMPORT", "false").lower() == "true",
        "pipelineId": pipeline_id,
        "projectName": project_name,
        "projectNameSource": project_name_source,
        "projectNameRemark": project_name_remark,
        "projectKey": project_key,
        "projectId": project_id,
        "projectConfigSource": _project_config_source(params, project_config, project_key, project_name_source),
        "projectRemark": (project_config or {}).get("remark"),
        "openapiUrl": openapi_url,
        "upstreamOpenapiUrl": upstream_openapi_url,
        "stripProjectPath": strip_project_path,
        "baseUrl": os.getenv("APIFOX_BASE_URL", "https://api.apifox.com"),
        "apiVersion": os.getenv("APIFOX_API_VERSION", "2024-03-28"),
        "locale": os.getenv("APIFOX_LOCALE", "zh-CN"),
        "accessToken": os.getenv("APIFOX_ACCESS_TOKEN"),
        "endpointOverwriteBehavior": os.getenv("APIFOX_ENDPOINT_OVERWRITE_BEHAVIOR", "OVERWRITE_EXISTING"),
        "schemaOverwriteBehavior": os.getenv("APIFOX_SCHEMA_OVERWRITE_BEHAVIOR", "KEEP_EXISTING"),
    }


def _import_openapi(config: dict[str, Any]) -> dict[str, Any]:
    url = f"{config['baseUrl'].rstrip('/')}/v1/projects/{config['projectId']}/import-openapi?locale={config['locale']}"
    payload = {
        "input": {"url": config["openapiUrl"]},
        "options": {
            "endpointOverwriteBehavior": config["endpointOverwriteBehavior"],
            "schemaOverwriteBehavior": config["schemaOverwriteBehavior"],
            "updateFolderOfChangedEndpoint": True,
            "prependBasePath": False,
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "X-Apifox-Api-Version": config["apiVersion"],
            "Authorization": f"Bearer {config['accessToken']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"statusCode": response.status, "body": _parse_json(body)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"statusCode": exc.code, "body": _parse_json(body), "error": "HTTPError"}
    except urllib.error.URLError as exc:
        return {"statusCode": None, "body": None, "error": str(exc)}


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:1000]


def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key != "accessToken"}


def _preflight_openapi(project_name: str) -> dict[str, Any]:
    try:
        spec = fetch_sanitized_openapi(project_name)
        return {"ok": True, "pathCount": len(spec.get("paths") or {})}
    except Exception as exc:
        return {"ok": False, "statusCode": None, "error": str(exc)}


def fetch_sanitized_openapi(project_name: str) -> dict[str, Any]:
    if project_name == "_empty":
        return {"openapi": "3.1.0", "info": {"title": "empty-api-cleanup", "version": "1.0.0"}, "paths": {}}
    upstream_url = _openapi_url_from_template(project_name, _normalize_key(project_name))
    with urllib.request.urlopen(upstream_url, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError:
        payload = body
    spec = _unwrap_openapi_payload(payload)
    _validate_openapi_spec(spec)
    return strip_project_path_from_openapi(spec, project_name)


def _unwrap_openapi_payload(payload: Any) -> dict[str, Any]:
    current = payload
    for _ in range(4):
        if isinstance(current, dict):
            return current
        if not isinstance(current, str):
            break
        next_value = _unwrap_string_payload(current)
        if next_value == current:
            break
        current = next_value
    raise OpenapiValidationError("upstream OpenAPI response is not an object")


def _unwrap_string_payload(value: str) -> Any:
    text = value.strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return text
    return decoded


def _validate_openapi_spec(spec: dict[str, Any]) -> None:
    if not isinstance(spec, dict):
        raise OpenapiValidationError("upstream OpenAPI response is not an object")
    if not (spec.get("openapi") or spec.get("swagger")):
        code = spec.get("code")
        msg = spec.get("msg") or spec.get("message") or spec.get("error")
        detail = f": code={code} msg={msg}" if code or msg else ""
        raise OpenapiValidationError(f"upstream did not return an OpenAPI document{detail}")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenapiValidationError("upstream OpenAPI document has no paths")


def strip_project_path_from_openapi(spec: dict[str, Any], project_name: str) -> dict[str, Any]:
    prefix = "/" + str(project_name or "").strip("/")
    if not prefix or prefix == "/":
        return spec
    result = dict(spec)
    paths = spec.get("paths") or {}
    rewritten: dict[str, Any] = {}
    for path, item in paths.items():
        new_path = _strip_path_prefix(str(path), prefix)
        rewritten[new_path] = item
    result["paths"] = rewritten
    result["servers"] = [{"url": prefix}]
    return result


def _strip_path_prefix(path: str, prefix: str) -> str:
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        return path[len(prefix) :]
    return path


def _adapter_openapi_url(project_name: str) -> str:
    base_url = os.getenv("ADAPTER_PUBLIC_BASE_URL", "http://47.116.102.238:18080").rstrip("/")
    return f"{base_url}/adapter/openapi/{project_name}"


def _find_project_config(project_name: str) -> dict[str, Any] | None:
    return db.find_apifox_project_config(project_name)


def _find_pipeline_config(pipeline_id: str) -> dict[str, Any] | None:
    return db.find_apifox_pipeline_config(pipeline_id)


def _project_config_source(
    params: dict[str, Any],
    project_config: dict[str, Any] | None,
    project_key: str,
    project_name_source: str,
) -> str:
    if _pick(params, "APIFOX_PROJECT_ID"):
        return "payload"
    if project_config and project_config.get("apifoxProjectId"):
        return "database"
    if os.getenv(f"APIFOX_PROJECT_{project_key}_ID"):
        return "environment_project"
    if project_name_source == "default" and (os.getenv("APIFOX_DEFAULT_PROJECT_ID") or os.getenv("APIFOX_PROJECT_ID")):
        return "environment_default"
    return "unresolved"


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def _source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        return sources[0]
    return payload


def _task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task")
    return task if isinstance(task, dict) else payload


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


def _repo_name(repo: str) -> str | None:
    if not repo:
        return None
    name = repo.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _normalize_key(value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "default")).strip("_").upper()
    return normalized or "DEFAULT"


def _openapi_url_from_template(project_name: str, project_key: str) -> str:
    template = os.getenv(
        "APIFOX_OPENAPI_URL_TEMPLATE",
        "https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs",
    )
    return template.format(project=project_name, projectKey=project_key, service=project_name)
