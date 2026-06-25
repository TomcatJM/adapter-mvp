import os

from fastapi import Header, HTTPException, status


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """要求API令牌。"""
    expected = os.getenv("ADAPTER_API_TOKEN")
    if not expected:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization[len(prefix) :]
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bearer token",
        )


def require_execute_approval(params: dict) -> None:
    """要求执行审批。"""
    approval_id = params.get("approvalId")
    approved = params.get("approved") is True
    if approval_id or approved:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Execute requires approvalId or approved=true",
    )
