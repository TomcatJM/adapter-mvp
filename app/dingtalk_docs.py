from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from string import Template
from typing import Any

from app import db


DEFAULT_AUTH_ENDPOINT = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
DEFAULT_TOKEN_HEADER = "x-acs-dingtalk-access-token"
DEFAULT_DOC_INFO_ENDPOINT_TEMPLATE = (
    "https://api.dingtalk.com/v2.0/wiki/nodes/{nodeIdEncoded}"
    "?withStatisticalInfo=false&withPermissionRole=false&operatorId={operatorIdEncoded}"
)
DEFAULT_USER_DETAIL_ENDPOINT_TEMPLATE = "https://api.dingtalk.com/v1.0/contact/users/{userIdEncoded}"
DEFAULT_OAPI_AUTH_ENDPOINT_TEMPLATE = "https://oapi.dingtalk.com/gettoken?appkey={appKeyEncoded}&appsecret={appSecretEncoded}"
DEFAULT_OAPI_USER_DETAIL_ENDPOINT = "https://oapi.dingtalk.com/topapi/v2/user/get"
NODE_RE = re.compile(r"alidocs\.dingtalk\.com/i/nodes/([^/?#\s]+)")
SAFE_NODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SECRET_RE = re.compile(
    r"(?i)(token|secret|password|passwd|cookie|authorization|access[_-]?key)([=:]\s*)[^\s,;]+"
)


class DingTalkDocError(RuntimeError):
    """钉钉文档读取异常。"""
    pass


def read_dingtalk_doc(
    *,
    url: str | None = None,
    node_id: str | None = None,
    sheet_id: str | None = None,
    workbook_id: str | None = None,
    cell_range: str = "A1:J50",
    timeout: int = 60,
    config_name: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """读取钉钉文档。"""
    node = extract_node_id(url=url, node_id=node_id)
    explicit_resource_id = _validate_resource_id(workbook_id) if workbook_id else None
    safe_timeout = max(5, min(int(timeout or 60), 180))
    config = _load_config(config_name)
    token = _get_access_token(config, safe_timeout)

    info, info_error = _read_doc_info(config, token, node, sheet_id, cell_range, safe_timeout, bool(kind))
    extension = _normalize_kind(kind or _pick(info, "extension", "fileExtension", "type", "kind", default=""))
    if not extension:
        detail = f"; doc_info failed: {info_error}" if info_error else ""
        raise DingTalkDocError(f"DingTalk document kind is unknown; configure doc_info endpoint or pass kind{detail}")
    resource_id = explicit_resource_id or _resolve_document_id(node, info)

    if extension == "adoc":
        document = _call_required_endpoint(config, "doc_read", token, resource_id, sheet_id, cell_range, safe_timeout)
        return {
            "ok": True,
            "nodeId": node,
            "documentId": resource_id,
            "extension": extension,
            "kind": "document",
            "configName": config["configName"],
            "metadata": _safe_metadata(info),
            "document": document,
        }

    if extension == "axls":
        try:
            sheet_list = _call_required_endpoint(config, "sheet_list", token, resource_id, sheet_id, cell_range, safe_timeout)
        except DingTalkDocError as exc:
            raise _with_doc_info_context(exc, info_error) from exc
        sheets = _extract_sheets(sheet_list)
        selected_sheet_id = sheet_id or _first_sheet_id(sheets)
        if not selected_sheet_id:
            raise DingTalkDocError("No sheet id found in DingTalk sheet metadata")
        try:
            range_result = _call_required_endpoint(
                config,
                "sheet_range",
                token,
                resource_id,
                selected_sheet_id,
                cell_range,
                safe_timeout,
            )
        except DingTalkDocError as exc:
            raise _with_doc_info_context(exc, info_error) from exc
        return {
            "ok": True,
            "nodeId": node,
            "workbookId": resource_id,
            "extension": extension,
            "kind": "sheet",
            "configName": config["configName"],
            "metadata": _safe_metadata(info),
            "sheets": sheets,
            "sheetId": selected_sheet_id,
            "range": cell_range,
            "rangeResult": range_result,
        }

    raise DingTalkDocError(f"Unsupported DingTalk doc kind: {extension}")


def resolve_dingtalk_operator(
    *,
    user_id: str,
    config_name: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """解析钉钉操作者。"""
    safe_user_id = _validate_user_id(user_id)
    safe_timeout = max(5, min(int(timeout or 60), 180))
    config = _load_config(config_name)
    token = _get_access_token(config, safe_timeout)
    endpoint = _render_template(
        os.getenv("DINGTALK_USER_DETAIL_URL_TEMPLATE") or DEFAULT_USER_DETAIL_ENDPOINT_TEMPLATE,
        {
            "userId": safe_user_id,
            "userIdEncoded": urllib.parse.quote(safe_user_id, safe=""),
        },
    )
    try:
        user_detail = _request_json("GET", endpoint, None, _auth_headers(config, token), safe_timeout)
        source = "contact_v1"
    except DingTalkDocError as exc:
        if not _should_fallback_to_oapi_user_detail(str(exc)):
            raise
        user_detail = _request_oapi_user_detail(config, safe_user_id, safe_timeout)
        source = "oapi_v2"
    union_id = str(_pick(user_detail, "unionId", "unionid", default="") or "").strip()
    if not union_id:
        raise DingTalkDocError("DingTalk user detail response did not include unionId")
    return {
        "configName": config["configName"],
        "appName": config.get("appName"),
        "userId": safe_user_id,
        "unionId": union_id,
        "source": source,
    }


def extract_node_id(*, url: str | None = None, node_id: str | None = None) -> str:
    """提取节点ID。"""
    raw = (node_id or "").strip()
    if raw:
        if not SAFE_NODE_RE.match(raw):
            raise DingTalkDocError("Invalid DingTalk node id")
        return raw
    value = (url or "").strip()
    match = NODE_RE.search(value)
    if not match:
        raise DingTalkDocError("Cannot extract DingTalk node id from URL")
    node = match.group(1)
    if not SAFE_NODE_RE.match(node):
        raise DingTalkDocError("Invalid DingTalk node id")
    return node


def _load_config(config_name: str | None) -> dict[str, Any]:
    """内部辅助函数：加载配置。"""
    name = (config_name or os.getenv("DINGTALK_DEFAULT_CONFIG_NAME") or "default").strip()
    config = db.find_dingtalk_app_config(name)
    if not config:
        raise DingTalkDocError(f"DingTalk app config is missing: {name}")
    if not config.get("appKey") or not config.get("appSecret"):
        raise DingTalkDocError(f"DingTalk app key/secret is incomplete: {name}")
    return config


def _get_access_token(config: dict[str, Any], timeout: int) -> str:
    """内部辅助函数：获取access令牌。"""
    cached = str(config.get("accessToken") or "")
    expires_at = _parse_datetime(config.get("tokenExpiresAt"))
    if cached and expires_at and expires_at > _now_utc() + timedelta(minutes=2):
        return cached

    endpoint = config.get("authEndpoint") or DEFAULT_AUTH_ENDPOINT
    payload = {
        "appKey": config["appKey"],
        "appSecret": config["appSecret"],
    }
    response = _request_json("POST", endpoint, payload, {}, timeout)
    token = str(_pick(response, "accessToken", "access_token", default="") or "")
    if not token:
        raise DingTalkDocError("DingTalk access token response did not include accessToken")
    expires_in = int(_pick(response, "expireIn", "expiresIn", "expires_in", default=7200) or 7200)
    expires_at = _now_utc() + timedelta(seconds=max(60, expires_in - 120))
    db.update_dingtalk_token_cache(config["configName"], token, expires_at)
    return token


def _call_required_endpoint(
    config: dict[str, Any],
    prefix: str,
    token: str,
    node_id: str,
    sheet_id: str | None,
    cell_range: str,
    timeout: int,
) -> Any:
    """内部辅助函数：callrequiredendpoint。"""
    result = _call_endpoint(config, prefix, token, node_id, sheet_id, cell_range, timeout)
    if result is None:
        raise DingTalkDocError(f"DingTalk endpoint is not configured: {prefix}")
    return result


def _call_endpoint(
    config: dict[str, Any],
    prefix: str,
    token: str,
    node_id: str,
    sheet_id: str | None,
    cell_range: str,
    timeout: int,
) -> Any:
    """内部辅助函数：callendpoint。"""
    template = config.get(f"{prefix}UrlTemplate")
    if not template and prefix == "doc_info" and config.get("operatorId"):
        template = DEFAULT_DOC_INFO_ENDPOINT_TEMPLATE
    if not template:
        return None
    method = str(config.get(f"{prefix}Method") or "GET").upper()
    context = _template_context(token, node_id, sheet_id, cell_range, config.get("operatorId"))
    url = _render_template(str(template), context)
    body_template = config.get(f"{prefix}BodyTemplate")
    payload = _render_body(body_template, context) if body_template is not None else None
    headers = _auth_headers(config, token)
    try:
        return _request_json(method, url, payload, headers, timeout)
    except DingTalkDocError as exc:
        raise DingTalkDocError(f"DingTalk {prefix} failed: {exc}") from exc


def _read_doc_info(
    config: dict[str, Any],
    token: str,
    node_id: str,
    sheet_id: str | None,
    cell_range: str,
    timeout: int,
    required: bool,
) -> tuple[Any, str | None]:
    """内部辅助函数：读取文档信息。"""
    try:
        return _call_endpoint(config, "doc_info", token, node_id, sheet_id, cell_range, timeout), None
    except DingTalkDocError as exc:
        if required:
            return {}, str(exc)
        raise


def _resolve_document_id(node_id: str, info: Any) -> str:
    """内部辅助函数：解析文档ID。"""
    value = _pick(info, "workbookId", "documentId", "docId", "nodeId", "dentryUuid", default="")
    resolved = str(value or "").strip()
    return _validate_resource_id(resolved) if resolved else node_id


def _validate_resource_id(value: str) -> str:
    """内部辅助函数：校验resourceID。"""
    resource_id = str(value or "").strip()
    if not SAFE_NODE_RE.match(resource_id):
        raise DingTalkDocError("Invalid DingTalk document resource id")
    return resource_id


def _with_doc_info_context(exc: DingTalkDocError, info_error: str | None) -> DingTalkDocError:
    """内部辅助函数：with文档信息上下文。"""
    if not info_error:
        return exc
    return DingTalkDocError(f"{exc}; doc_info failed before fallback: {info_error}")


def _request_json(method: str, url: str, payload: Any, headers: dict[str, str], timeout: int) -> Any:
    """内部辅助函数：请求JSON。"""
    data = None
    request_headers = {"Accept": "application/json", **headers}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, method=method.upper(), headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return _parse_json(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = _sanitize(_parse_error_detail(body) or str(exc))
        raise DingTalkDocError(f"DingTalk API failed: status={exc.code} {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise DingTalkDocError(f"DingTalk API network error: {_sanitize(str(exc))[:1000]}") from exc


def _request_oapi_user_detail(config: dict[str, Any], user_id: str, timeout: int) -> Any:
    """内部辅助函数：请求oapiuser详情。"""
    token = _get_oapi_access_token(config, timeout)
    endpoint = os.getenv("DINGTALK_OAPI_USER_DETAIL_ENDPOINT") or DEFAULT_OAPI_USER_DETAIL_ENDPOINT
    payload = {"userid": user_id, "language": "zh_CN"}
    response = _request_json(
        "POST",
        _append_query(endpoint, {"access_token": token}),
        payload,
        {},
        timeout,
    )
    _raise_oapi_error(response, "DingTalk oapi user detail failed")
    return response


def _get_oapi_access_token(config: dict[str, Any], timeout: int) -> str:
    """内部辅助函数：获取oapiaccess令牌。"""
    endpoint = _render_template(
        os.getenv("DINGTALK_OAPI_AUTH_ENDPOINT_TEMPLATE") or DEFAULT_OAPI_AUTH_ENDPOINT_TEMPLATE,
        {
            "appKey": config["appKey"],
            "appKeyEncoded": urllib.parse.quote(str(config["appKey"]), safe=""),
            "appSecret": config["appSecret"],
            "appSecretEncoded": urllib.parse.quote(str(config["appSecret"]), safe=""),
        },
    )
    response = _request_json("GET", endpoint, None, {}, timeout)
    _raise_oapi_error(response, "DingTalk oapi token failed")
    token = str(_pick(response, "accessToken", "access_token", default="") or "")
    if not token:
        raise DingTalkDocError("DingTalk oapi token response did not include access_token")
    return token


def _raise_oapi_error(response: Any, prefix: str) -> None:
    """内部辅助函数：raiseoapi错误。"""
    if not isinstance(response, dict):
        return
    errcode = response.get("errcode")
    if errcode in (None, 0, "0"):
        return
    detail = _sanitize(str(response.get("errmsg") or response.get("message") or response))
    raise DingTalkDocError(f"{prefix}: errcode={errcode} {detail[:1000]}")


def _append_query(url: str, params: dict[str, str]) -> str:
    """内部辅助函数：appendquery。"""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _should_fallback_to_oapi_user_detail(message: str) -> bool:
    """内部辅助函数：shouldfallbacktooapiuser详情。"""
    return "status=404" in message or "找不到该用户" in message


def _auth_headers(config: dict[str, Any], token: str) -> dict[str, str]:
    """内部辅助函数：鉴权headers。"""
    header_name = str(config.get("tokenHeaderName") or DEFAULT_TOKEN_HEADER).strip()
    if not header_name:
        return {}
    return {header_name: token}


def _template_context(
    token: str,
    node_id: str,
    sheet_id: str | None,
    cell_range: str,
    operator_id: str | None,
) -> dict[str, str]:
    """内部辅助函数：模板上下文。"""
    operator = operator_id or ""
    return {
        "accessToken": token,
        "nodeId": node_id,
        "nodeIdEncoded": urllib.parse.quote(node_id, safe=""),
        "sheetId": sheet_id or "",
        "sheetIdEncoded": urllib.parse.quote(sheet_id or "", safe=""),
        "range": cell_range,
        "rangeEncoded": urllib.parse.quote(cell_range, safe=""),
        "operatorId": operator,
        "operatorIdEncoded": urllib.parse.quote(operator, safe=""),
    }


def _validate_user_id(value: str) -> str:
    """内部辅助函数：校验userID。"""
    user_id = str(value or "").strip()
    if not user_id:
        raise DingTalkDocError("DingTalk userId is required")
    if len(user_id) > 128 or any(ord(char) < 32 for char in user_id):
        raise DingTalkDocError("Invalid DingTalk userId")
    return user_id


def _render_template(value: str, context: dict[str, str]) -> str:
    """内部辅助函数：render模板。"""
    rendered = Template(value).safe_substitute(context)
    for key, item in context.items():
        rendered = rendered.replace("{" + key + "}", item)
    return rendered


def _render_body(value: Any, context: dict[str, str]) -> Any:
    """内部辅助函数：render正文。"""
    if isinstance(value, str):
        rendered = _render_template(value, context)
        return json.loads(rendered) if rendered.strip() else None
    return _render_json_value(value, context)


def _render_json_value(value: Any, context: dict[str, str]) -> Any:
    """内部辅助函数：renderJSON值。"""
    if isinstance(value, str):
        return _render_template(value, context)
    if isinstance(value, list):
        return [_render_json_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_json_value(item, context) for key, item in value.items()}
    return value


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
        return str(_pick(parsed, "message", "msg", "errorMessage", "error", default=text[:1000]))
    return str(parsed)


def _normalize_kind(value: str) -> str:
    """内部辅助函数：归一化kind。"""
    kind = str(value or "").lower().strip()
    if kind in {"doc", "document", "adoc"}:
        return "adoc"
    if kind in {"sheet", "spreadsheet", "axls", "xls", "xlsx"}:
        return "axls"
    return kind


def _pick(payload: Any, *keys: str, default: Any = None) -> Any:
    """pick。"""
    for source in _dict_candidates(payload):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return default


def _safe_metadata(info: Any) -> dict[str, Any]:
    """内部辅助函数：安全metadata。"""
    allowed = {
        "nodeId",
        "name",
        "title",
        "extension",
        "fileExtension",
        "type",
        "kind",
        "createdAt",
        "updatedAt",
        "owner",
    }
    metadata: dict[str, Any] = {}
    for source in _dict_candidates(info):
        metadata.update({key: value for key, value in source.items() if key in allowed})
    return metadata


def _dict_candidates(payload: Any):
    """内部辅助函数：dictcandidates。"""
    if not isinstance(payload, dict):
        return
    yield payload
    for key in ("data", "result", "metadata", "node", "doc", "document"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            yield nested


def _extract_sheets(sheet_list: Any) -> list[dict[str, Any]]:
    """内部辅助函数：提取sheets。"""
    raw_sheets: Any = sheet_list
    if isinstance(sheet_list, dict):
        raw_sheets = (
            sheet_list.get("sheets")
            or sheet_list.get("value")
            or sheet_list.get("data")
            or sheet_list.get("items")
            or sheet_list.get("result")
            or []
        )
    if isinstance(raw_sheets, dict):
        raw_sheets = raw_sheets.get("sheets") or raw_sheets.get("items") or []
    if not isinstance(raw_sheets, list):
        return []
    sheets: list[dict[str, Any]] = []
    for item in raw_sheets:
        if not isinstance(item, dict):
            continue
        sid = item.get("sheetId") or item.get("id") or item.get("sheet_id")
        if not sid:
            continue
        sheets.append(
            {
                "sheetId": str(sid),
                "name": item.get("name") or item.get("title") or item.get("sheetName"),
            }
        )
    return sheets


def _first_sheet_id(sheets: list[dict[str, Any]]) -> str | None:
    """内部辅助函数：第一个sheetID。"""
    if not sheets:
        return None
    value = sheets[0].get("sheetId")
    return str(value) if value else None


def _parse_datetime(value: Any) -> datetime | None:
    """内部辅助函数：解析datetime。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_utc() -> datetime:
    """内部辅助函数：nowutc。"""
    return datetime.now(timezone.utc)


def _sanitize(text: str) -> str:
    """sanitize。"""
    return SECRET_RE.sub(r"\1\2***", text)
