import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app import db
from app.models import (
    AdapterPreview,
    AdapterRequest,
    AdapterResult,
    AdapterStatus,
    YunxiaoPipelineFailureCallback,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "logs" / "audit.jsonl"
_lock = Lock()


def log_preview(request: AdapterRequest, preview: AdapterPreview) -> None:
    """记录预览事件。"""
    _write(
        {
            "event": "preview",
            **_request_fields(request),
            "blocked": preview.blocked,
            "risk": preview.risk,
            "needApproval": preview.need_approval,
            "status": "BLOCKED" if preview.blocked else "PREVIEWED",
            "reason": preview.reason,
        }
    )


def log_execute(request: AdapterRequest, result: AdapterResult) -> None:
    """记录执行事件。"""
    _write(
        {
            "event": "execute",
            **_request_fields(request),
            "status": result.status,
            "message": result.message,
            "elapsedMs": result.data.get("elapsedMs"),
        }
    )


def log_status(task_id: str, status: AdapterStatus) -> None:
    """记录状态查询事件。"""
    _write(
        {
            "event": "status",
            "taskId": task_id,
            "status": status.status,
            "message": status.message,
        }
    )


def log_pipeline_failure(callback: YunxiaoPipelineFailureCallback, analysis: dict[str, Any]) -> None:
    """记录流水线失败事件。"""
    _write(
        {
            "event": "pipeline_failure",
            "taskId": callback.task_id,
            "operator": callback.operator,
            "status": "ANALYSIS_READY",
            "message": analysis.get("summary"),
            "pipelineId": callback.pipeline_id,
            "buildNumber": callback.build_number,
            "stageName": callback.stage_name,
            "branchName": callback.branch_name,
            "commitId": callback.commit_id,
            "exitCode": callback.exit_code,
            "category": analysis.get("category"),
            "confidence": analysis.get("confidence"),
            "logUrl": callback.log_url,
            "logTail": _truncate(callback.log_tail, 8000),
            "analysis": analysis,
        }
    )


def log_apifox_import(task_id: str, operator: str, result: dict[str, Any]) -> None:
    """记录 Apifox 导入事件。"""
    _write(
        {
            "event": "apifox_import",
            "taskId": task_id,
            "operator": operator,
            "status": "IMPORTED" if result.get("imported") else "SKIPPED",
            "message": result.get("reason") or "Apifox import finished",
            "projectKey": result.get("projectKey"),
            "projectId": result.get("projectId"),
            "openapiUrl": result.get("openapiUrl"),
            "payload": result,
        }
    )


def log_webhook_error(source: str, payload: dict[str, Any], exc: Exception) -> None:
    """记录 webhook 错误事件。"""
    task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
    task_id = task.get("taskId") or task.get("task_id")
    pipeline_id = task.get("pipelineId") or task.get("pipeline_id") or task.get("flowId") or task.get("flow_id")
    build_number = task.get("buildNumber") or task.get("build_number") or task.get("buildNo") or task.get("build_no")
    _write(
        {
            "event": "webhook_error",
            "taskId": str(task_id or f"yx-flow-{pipeline_id or 'unknown'}-{build_number or '0'}"),
            "operator": "yunxiao",
            "status": "FAILED",
            "message": f"{type(exc).__name__}: {str(exc)}"[:1024],
            "pipelineId": pipeline_id,
            "buildNumber": build_number,
            "source": source,
            "payload": payload,
        }
    )


def find_by_task_id(task_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """查找by任务ID。"""
    rows = _find_db(task_id, limit)
    if rows:
        return rows
    return _find_file(task_id, limit)


def _request_fields(request: AdapterRequest) -> dict[str, Any]:
    """内部辅助函数：请求fields。"""
    params = request.params or {}
    return {
        "taskId": request.task_id,
        "operator": request.operator,
        "system": request.system,
        "action": request.action,
        "env": request.env,
        "hostId": params.get("hostId"),
        "approvalId": params.get("approvalId"),
        "approved": params.get("approved") is True,
    }


def _truncate(value: str | None, max_length: int) -> str | None:
    """truncate。"""
    if value is None:
        return None
    if len(value) <= max_length:
        return value
    return value[-max_length:]


def _write(item: dict[str, Any]) -> None:
    """写入。"""
    safe_item = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **{key: value for key, value in item.items() if value is not None},
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(safe_item, ensure_ascii=False, separators=(",", ":"))
    with _lock:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    _write_db(safe_item)


def _write_db(item: dict[str, Any]) -> None:
    """内部辅助函数：写入数据库。"""
    if not db.configured():
        return
    try:
        db.ensure_schema()
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO adapter_audit (
                        event, task_id, operator, system_name, action_name, env_name,
                        host_id, approval_id, approved, status, message, elapsed_ms, payload_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON)
                    )
                    """,
                    (
                        item.get("event"),
                        item.get("taskId"),
                        item.get("operator"),
                        item.get("system"),
                        item.get("action"),
                        item.get("env"),
                        item.get("hostId"),
                        item.get("approvalId"),
                        int(item["approved"]) if "approved" in item else None,
                        item.get("status"),
                        item.get("message"),
                        item.get("elapsedMs"),
                        db.dumps(item),
                    ),
                )
    except Exception:
        return


def _find_db(task_id: str, limit: int) -> list[dict[str, Any]]:
    """内部辅助函数：查找数据库。"""
    if not db.configured():
        return []
    try:
        db.ensure_schema()
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, ts, event, task_id, operator, system_name, action_name, env_name,
                           host_id, approval_id, approved, status, message, elapsed_ms
                    FROM adapter_audit
                    WHERE task_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (task_id, int(limit)),
                )
                rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "id": row.get("id"),
                    "ts": row.get("ts").isoformat() if row.get("ts") else None,
                    "event": row.get("event"),
                    "taskId": row.get("task_id"),
                    "operator": row.get("operator"),
                    "system": row.get("system_name"),
                    "action": row.get("action_name"),
                    "env": row.get("env_name"),
                    "hostId": row.get("host_id"),
                    "approvalId": row.get("approval_id"),
                    "approved": bool(row["approved"]) if row.get("approved") is not None else None,
                    "status": row.get("status"),
                    "message": row.get("message"),
                    "elapsedMs": row.get("elapsed_ms"),
                }
            )
        return result
    except Exception:
        return []


def _find_file(task_id: str, limit: int) -> list[dict[str, Any]]:
    """内部辅助函数：查找file。"""
    if not AUDIT_PATH.exists():
        return []
    result = []
    with AUDIT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("taskId") == task_id:
                result.append(item)
    return list(reversed(result[-int(limit) :]))
