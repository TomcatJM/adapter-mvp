from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app import db


class KnowledgeQueryError(ValueError):
    """知识图谱查询错误。"""


def query_knowledge(
    *,
    project_key: str,
    question: str,
    mode: str = "ai",
    timeout: int = 30,
) -> dict[str, Any]:
    """通过项目配置代理查询知识图谱。"""
    normalized_project_key = str(project_key or "").strip()
    normalized_question = str(question or "").strip()
    normalized_mode = str(mode or "ai").strip() or "ai"
    if not normalized_project_key:
        raise KnowledgeQueryError("projectKey is required")
    if not normalized_question:
        raise KnowledgeQueryError("question is required")

    project_config = db.find_adapter_project_config(normalized_project_key)
    if not project_config:
        raise KnowledgeQueryError(f"Adapter project config not found: {normalized_project_key}")
    endpoint = str(project_config.get("knowledgeEndpoint") or "").strip()
    if not endpoint:
        raise KnowledgeQueryError(f"Knowledge endpoint is not configured: {normalized_project_key}")

    payload = _read_json(_with_query(endpoint, {"question": normalized_question, "mode": normalized_mode}), timeout)
    return _normalize_knowledge_response(
        payload,
        project_key=project_config.get("projectKey") or normalized_project_key,
        question=normalized_question,
        mode=normalized_mode,
    )


def _with_query(endpoint: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    existing = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = urllib.parse.urlencode(existing + list(params.items()))
    return urllib.parse.urlunparse(parsed._replace(query=query))


def _read_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise KnowledgeQueryError(f"Knowledge query failed: {exc}") from exc
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise KnowledgeQueryError("Knowledge query response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise KnowledgeQueryError("Knowledge query response must be a JSON object")
    return data


def _normalize_knowledge_response(
    data: dict[str, Any],
    *,
    project_key: str,
    question: str,
    mode: str,
) -> dict[str, Any]:
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    source = nested or data
    return {
        "projectKey": project_key,
        "question": question,
        "mode": mode,
        "businessAnswer": source.get("businessAnswer") or source.get("answer") or "",
        "developerEntrypoints": _as_list(source.get("developerEntrypoints")),
        "aiPlanHints": _as_list(source.get("aiPlanHints")),
        "documents": _as_list(source.get("documents")),
        "raw": data,
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
