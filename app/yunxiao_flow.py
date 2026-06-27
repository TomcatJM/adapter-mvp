from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app import db


PERSONAL_TOKEN_ENDPOINT = "openapi-rdc.aliyuncs.com"


class YunxiaoFlowError(RuntimeError):
    """YunxiaoFlowError 异常类型。"""
    pass


def discover_project_from_pipeline(pipeline_id: str) -> dict[str, Any]:
    """从流水线发现项目。"""
    pipeline_id = _clean_text(pipeline_id)
    if not pipeline_id:
        return {"matched": False, "reason": "missing pipelineId"}
    project_configs = db.list_apifox_project_configs()
    if not project_configs:
        return {"matched": False, "reason": "no Apifox project config to match against"}

    errors: list[str] = []
    for yunxiao_project in db.list_yunxiao_project_configs():
        try:
            account = _load_personal_token_account(yunxiao_project)
            pipeline = get_pipeline(
                organization_id=str(yunxiao_project["organizationId"]),
                pipeline_id=pipeline_id,
                account=account,
            )
        except YunxiaoFlowError as exc:
            errors.append(str(exc))
            continue

        match = _match_project_from_pipeline(pipeline, project_configs)
        if not match:
            errors.append(
                "pipeline detail returned but no configured Apifox project matched: "
                f"pipelineId={pipeline_id}, yunxiaoProject={yunxiao_project.get('projectName')}"
            )
            continue

        pipeline_name = _pipeline_name(pipeline)
        service_name = _service_name_from_pipeline(pipeline) or _normalize_name(match["projectName"]) or match["projectName"]
        env_name = _env_name_from_pipeline(pipeline) or "dev-uat"
        repo_name = _repo_name_from_pipeline(pipeline)
        remark = _pipeline_cache_remark(pipeline, yunxiao_project, match)
        db.upsert_apifox_pipeline_config(
            pipeline_id,
            match["apifoxProjectConfigId"],
            pipeline_name=pipeline_name,
            service_name=service_name,
            env_name=env_name,
            repo_name=repo_name,
            remark=remark,
        )
        return {
            "matched": True,
            "pipelineId": pipeline_id,
            "projectName": match["projectName"],
            "apifoxProjectConfigId": match["apifoxProjectConfigId"],
            "source": "yunxiao_pipeline",
            "remark": remark,
            "matchEvidence": match["evidence"],
            "pipelineName": pipeline_name,
            "serviceName": service_name,
            "envName": env_name,
            "repoName": repo_name,
            "yunxiaoProjectName": yunxiao_project.get("projectName"),
        }

    return {
        "matched": False,
        "pipelineId": pipeline_id,
        "reason": "unable to resolve project from Yunxiao pipeline",
        "errors": errors[:5],
    }


def get_pipeline(organization_id: str, pipeline_id: str, account: dict[str, Any]) -> dict[str, Any]:
    """获取流水线信息。"""
    organization_id = _clean_text(organization_id)
    pipeline_id = _clean_text(pipeline_id)
    token = _clean_text(account.get("personalToken"))
    if not organization_id or not pipeline_id or not token:
        raise YunxiaoFlowError("Yunxiao flow config missing organizationId, pipelineId, or personal token")

    endpoint = _clean_text(account.get("endpoint")) or PERSONAL_TOKEN_ENDPOINT
    scheme, host = _normalize_endpoint(endpoint)
    org = urllib.parse.quote(organization_id, safe="")
    pipe = urllib.parse.quote(pipeline_id, safe="")
    url = f"{scheme}://{host}/oapi/v1/flow/organizations/{org}/pipelines/{pipe}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"x-yunxiao-token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = _parse_json(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise YunxiaoFlowError(
            f"GetPipeline failed: status={exc.code} pipelineId={pipeline_id} detail={_safe_error(body)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise YunxiaoFlowError(f"GetPipeline failed: pipelineId={pipeline_id} error={exc.reason}") from exc

    if isinstance(payload, dict) and payload.get("errorCode"):
        raise YunxiaoFlowError(
            "GetPipeline failed: "
            f"pipelineId={pipeline_id} code={payload.get('errorCode')} message={payload.get('errorMessage')}"
        )
    return payload if isinstance(payload, dict) else {"raw": payload}


def _load_personal_token_account(yunxiao_project: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：加载personal令牌account。"""
    account_name = _clean_text(yunxiao_project.get("accountName"))
    if not account_name:
        raise YunxiaoFlowError(f"Yunxiao project account missing: {yunxiao_project.get('projectName')}")
    account = db.find_yunxiao_account_config(account_name)
    if not account:
        raise YunxiaoFlowError(f"Yunxiao account config missing: {account_name}")
    auth_type = str(account.get("authType") or "").strip().lower()
    if auth_type not in {"personal_token", "personal", "personal_access_token", "pat"}:
        raise YunxiaoFlowError(f"Yunxiao GetPipeline requires personal_token account: {account_name}")
    return {
        "endpoint": account.get("endpoint") or PERSONAL_TOKEN_ENDPOINT,
        "personalToken": account.get("legacyToken"),
    }


def _match_project_from_pipeline(
    pipeline: dict[str, Any],
    project_configs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """内部辅助函数：match项目来自流水线。"""
    evidence_text = "\n".join(_collect_pipeline_text(pipeline)).lower()
    candidates: list[dict[str, Any]] = []
    for config in project_configs:
        project_name = _clean_text(config.get("projectName"))
        config_id = config.get("apifoxProjectConfigId")
        if not project_name:
            continue
        needles = {project_name.lower(), _normalize_name(project_name)}
        if any(needle and needle in evidence_text for needle in needles):
            candidates.append(
                {
                    "projectName": project_name,
                    "apifoxProjectConfigId": config_id,
                    "evidence": _compact_evidence(evidence_text, project_name),
                }
            )

    if len(candidates) != 1:
        return None
    return candidates[0]


def _collect_pipeline_text(value: Any) -> list[str]:
    """内部辅助函数：collect流水线文本。"""
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"token", "secret", "password", "authorization"}:
                continue
            result.extend(_collect_pipeline_text(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_collect_pipeline_text(item))
    elif isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            result.append(cleaned)
    return result


def _pipeline_cache_remark(
    pipeline: dict[str, Any],
    yunxiao_project: dict[str, Any],
    match: dict[str, Any],
) -> str:
    """内部辅助函数：流水线缓存remark。"""
    parts = [
        "auto-discovered",
        f"yunxiaoProject={yunxiao_project.get('projectName') or ''}",
        f"pipelineName={_pipeline_name(pipeline) or ''}",
        f"evidence={match.get('evidence') or ''}",
    ]
    return "; ".join(part for part in parts if part and not part.endswith("="))[:512]


def _pipeline_name(pipeline: dict[str, Any]) -> str | None:
    """内部辅助函数：流水线name。"""
    for source in _dict_candidates(pipeline):
        value = _clean_text(source.get("name") or source.get("pipelineName"))
        if value:
            return value
    return None


def _service_name_from_pipeline(pipeline: dict[str, Any]) -> str | None:
    """从流水线名称推断服务名。"""
    name = _pipeline_name(pipeline)
    if not name:
        return None
    for marker in ("开发", "UAT", "部署"):
        if marker in name:
            return _clean_text(name.split(marker, 1)[0])
    return _clean_text(name)


def _env_name_from_pipeline(pipeline: dict[str, Any]) -> str | None:
    """从流水线名称推断环境名。"""
    name = (_pipeline_name(pipeline) or "").upper()
    has_dev = "开发" in name
    has_uat = "UAT" in name
    if has_dev and has_uat:
        return "dev-uat"
    if has_dev:
        return "dev"
    if has_uat:
        return "uat"
    return None


def _repo_name_from_pipeline(pipeline: dict[str, Any]) -> str | None:
    """从流水线详情中提取仓库名。"""
    for text in _collect_pipeline_text(pipeline):
        match = re.search(r"\bjdb-[A-Za-z0-9_-]+\b", text)
        if match:
            return match.group(0)
    return None


def _compact_evidence(text: str, project_name: str) -> str:
    """内部辅助函数：compactevidence。"""
    needle = project_name.lower()
    index = text.find(needle)
    if index < 0:
        index = text.find(_normalize_name(project_name))
    if index < 0:
        return project_name
    start = max(0, index - 40)
    end = min(len(text), index + len(project_name) + 40)
    return text[start:end].replace("\n", " ")[:160]


def _dict_candidates(payload: Any):
    """内部辅助函数：dictcandidates。"""
    if not isinstance(payload, dict):
        return
    yield payload
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            yield nested


def _parse_json(text: str) -> Any:
    """内部辅助函数：解析JSON。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:1000]


def _safe_error(text: str) -> str:
    """内部辅助函数：安全错误。"""
    parsed = _parse_json(text)
    if isinstance(parsed, dict):
        return str(
            {
                "errorCode": parsed.get("errorCode") or parsed.get("code"),
                "errorMessage": parsed.get("errorMessage") or parsed.get("message") or parsed.get("msg"),
            }
        )
    return str(parsed)[:500]


def _normalize_endpoint(value: str) -> tuple[str, str]:
    """内部辅助函数：归一化endpoint。"""
    raw = str(value or PERSONAL_TOKEN_ENDPOINT).strip().rstrip("/")
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        return parsed.scheme or "https", parsed.netloc
    return "https", raw


def _normalize_name(value: Any) -> str:
    """内部辅助函数：归一化name。"""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clean_text(value: Any) -> str | None:
    """内部辅助函数：清洗文本。"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
