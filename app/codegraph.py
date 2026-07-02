from typing import Any

from fastapi import HTTPException

from app import db
from app.models import CodeGraphIndexCallbackRequest


def handle_index_callback(request: CodeGraphIndexCallbackRequest) -> dict[str, Any]:
    """记录 CodeGraph 索引回调。"""
    project_config = db.find_adapter_project_config(request.project_key)
    if not project_config:
        raise HTTPException(
            status_code=400,
            detail=f"adapter_project_config not found for projectKey={request.project_key}",
        )

    index_status = _normalize_index_status(request.index_status)
    db.upsert_codegraph_index(
        project_key=request.project_key,
        branch_name=request.branch_name,
        commit_id=request.commit_id,
        index_version=request.index_version,
        storage_type=request.storage_type,
        bucket_name=request.bucket_name,
        object_key=request.object_key,
        status_object_key=request.status_object_key,
        sha256_object_key=request.sha256_object_key,
        index_status=index_status,
        stats=request.stats,
        error_message=request.error_message,
    )

    return {
        "ok": True,
        "projectKey": request.project_key,
        "branchName": request.branch_name,
        "commitId": request.commit_id,
        "indexVersion": request.index_version,
        "indexStatus": index_status,
        "workflowId": request.workflow_id,
        "workflowAdvanced": False,
    }


def _normalize_index_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in {"success", "failed"}:
        raise HTTPException(status_code=400, detail="indexStatus must be success or failed")
    return normalized
