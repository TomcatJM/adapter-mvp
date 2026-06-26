import hmac
import os

from fastapi import Header, HTTPException, status

from app import db


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """要求API令牌。"""
    expected = os.getenv("ADAPTER_API_TOKEN")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        if not expected and not db.configured():
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = authorization[len(prefix) :].strip()
    api_client = None
    db_lookup_failed = False
    try:
        api_client = db.find_api_client_by_token(token)
    except Exception:
        db_lookup_failed = True
    if api_client:
        return

    if expected and hmac.compare_digest(token, expected):
        return

    if not expected and not db.configured():
        return

    if db_lookup_failed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API token store unavailable",
        )

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
