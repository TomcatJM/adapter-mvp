from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app import db
from app.yunxiao_flow import discover_project_from_pipeline


class OpenapiValidationError(ValueError):
    pass


class OpenapiSignatureError(ValueError):
    pass


def maybe_import_from_flow_event(payload: dict[str, Any]) -> dict[str, Any]:
    config = _resolve_config(payload)
    safe_config = _safe_config(config)
    if not config["autoImport"]:
        return {"enabled": False, "imported": False, "reason": "APIFOX_AUTO_IMPORT is not true", **safe_config}
    if not config.get("projectId") and config["projectNameSource"] == "unresolved":
        return {
            "enabled": True,
            "imported": False,
            "reason": _missing_project_mapping_reason(config),
            **safe_config,
        }
    missing = [key for key in ("accessToken", "projectId", "openapiUrl") if not config.get(key)]
    if missing:
        return {"enabled": True, "imported": False, "reason": _missing_config_reason(config, missing), **safe_config}
    if config["stripProjectPath"] and config.get("projectName"):
        preflight = _preflight_openapi(config["projectName"], config.get("upstreamOpenapiUrl"))
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
    auto_import = os.getenv("APIFOX_AUTO_IMPORT", "false").lower() == "true"
    pipeline_id = str(_pick(task, "pipelineId", "pipeline_id", "pipelineID", "flowId", "flow_id", default=""))
    pipeline_config = _find_pipeline_config(pipeline_id)
    payload_project_name = _pick(params, "PROJECT_NAME", "SERVICE_NAME", "APP_NAME", "APIFOX_PROJECT_KEY")
    pipeline_discovery = None
    if auto_import and pipeline_id and not payload_project_name and not pipeline_config:
        pipeline_discovery = discover_project_from_pipeline(pipeline_id)
        if pipeline_discovery.get("matched"):
            pipeline_config = _find_pipeline_config(pipeline_id) or {
                "pipelineId": pipeline_id,
                "projectName": pipeline_discovery.get("projectName"),
                "remark": pipeline_discovery.get("remark"),
            }
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
        project_name = None
        project_name_source = "unresolved"
        project_name_remark = None
    project_key = _normalize_key(project_name)
    project_config = _find_project_config(project_name) if project_name else None
    project_id = (
        _pick(params, "APIFOX_PROJECT_ID")
        or (project_config or {}).get("apifoxProjectId")
        or (os.getenv(f"APIFOX_PROJECT_{project_key}_ID") if project_name else None)
    )
    payload_openapi_url = _pick(params, "OPENAPI_URL", "APIFOX_OPENAPI_URL")
    upstream_openapi_url = (
        payload_openapi_url
        or (project_config or {}).get("openapiUrl")
        or (os.getenv(f"OPENAPI_{project_key}_URL") if project_name else None)
        or os.getenv("OPENAPI_URL")
        or (_openapi_url_from_template(project_name, project_key) if project_name else None)
    )
    strip_project_path = os.getenv("APIFOX_STRIP_PROJECT_PATH", "true").lower() == "true"
    signed_upstream_url = str(payload_openapi_url) if payload_openapi_url else None
    openapi_url = (
        _adapter_openapi_url(project_name, signed_upstream_url)
        if strip_project_path and project_name
        else upstream_openapi_url
    )
    return {
        "autoImport": auto_import,
        "pipelineId": pipeline_id,
        "projectName": project_name,
        "projectNameSource": project_name_source,
        "projectNameRemark": project_name_remark,
        "pipelineDiscovery": pipeline_discovery,
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


def _preflight_openapi(project_name: str, upstream_url: str | None = None) -> dict[str, Any]:
    try:
        spec = fetch_sanitized_openapi(project_name, upstream_url=upstream_url)
        return {"ok": True, "pathCount": len(spec.get("paths") or {})}
    except Exception as exc:
        return {"ok": False, "statusCode": None, "error": str(exc)}


def fetch_sanitized_openapi(project_name: str, upstream_url: str | None = None) -> dict[str, Any]:
    if project_name == "_empty":
        return {"openapi": "3.1.0", "info": {"title": "empty-api-cleanup", "version": "1.0.0"}, "paths": {}}
    project_key = _normalize_key(project_name)
    project_config = _find_project_config(project_name)
    resolved_upstream_url = upstream_url or (
        (project_config or {}).get("openapiUrl")
        or os.getenv(f"OPENAPI_{project_key}_URL")
        or os.getenv("OPENAPI_URL")
        or _openapi_url_from_template(project_name, project_key)
    )
    with urllib.request.urlopen(resolved_upstream_url, timeout=30) as response:
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


def _adapter_openapi_url(project_name: str, upstream_url: str | None = None) -> str:
    base_url = os.getenv("ADAPTER_PUBLIC_BASE_URL", "http://47.116.102.238:18080").rstrip("/")
    url = f"{base_url}/adapter/openapi/{project_name}"
    if not upstream_url:
        return url
    secret = _openapi_url_signing_secret()
    if not secret:
        return upstream_url
    query = urllib.parse.urlencode(
        {
            "upstreamUrl": upstream_url,
            "signature": _sign_openapi_upstream(project_name, upstream_url, secret),
        }
    )
    return f"{url}?{query}"


def verify_signed_upstream_url(project_name: str, upstream_url: str | None, signature: str | None) -> str | None:
    if not upstream_url:
        return None
    secret = _openapi_url_signing_secret()
    if not secret or not signature:
        raise OpenapiSignatureError("missing OpenAPI upstream signature")
    expected = _sign_openapi_upstream(project_name, upstream_url, secret)
    if not hmac.compare_digest(expected, signature):
        raise OpenapiSignatureError("invalid OpenAPI upstream signature")
    return upstream_url


def _openapi_url_signing_secret() -> str | None:
    return os.getenv("APIFOX_OPENAPI_SIGNING_SECRET") or os.getenv("ADAPTER_API_TOKEN")


def _sign_openapi_upstream(project_name: str, upstream_url: str, secret: str) -> str:
    message = f"{project_name}\n{upstream_url}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


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
    if project_name_source != "unresolved" and os.getenv(f"APIFOX_PROJECT_{project_key}_ID"):
        return "environment_project"
    return "unresolved"


def _missing_project_mapping_reason(config: dict[str, Any]) -> str:
    pipeline_id = config.get("pipelineId") or "unknown"
    return (
        f"missing Apifox project mapping for pipelineId={pipeline_id}; "
        "pass APIFOX_PROJECT_ID with OPENAPI_URL, pass PROJECT_NAME/SERVICE_NAME/APP_NAME/APIFOX_PROJECT_KEY, "
        "or configure adapter_apifox_pipeline_config / APIFOX_PIPELINE_<PIPELINE_ID>_PROJECT. "
        "APIFOX_DEFAULT_PROJECT_ID is intentionally ignored."
    )


def _missing_config_reason(config: dict[str, Any], missing: list[str]) -> str:
    if missing == ["projectId"] and config.get("projectName"):
        return (
            f"missing Apifox project ID for projectName={config['projectName']} "
            f"(source={config['projectNameSource']}); configure adapter_apifox_project_config, "
            f"APIFOX_PROJECT_{config['projectKey']}_ID, or pass APIFOX_PROJECT_ID explicitly."
        )
    return f"missing {','.join(missing)}"


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
