import hmac
import os

from fastapi import Header, HTTPException, status

from app import db

DELETE_SCOPE = "yunxiao:delete"


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """要求API令牌。"""
    _authenticate_api_token(authorization, required_scope=None, allow_env_fallback=True)


def require_delete_api_token(authorization: str | None = Header(default=None)) -> None:
    """要求具备云效删除权限的API令牌。"""
    _authenticate_api_token(authorization, required_scope=DELETE_SCOPE, allow_env_fallback=False)


def _authenticate_api_token(
    authorization: str | None,
    *,
    required_scope: str | None,
    allow_env_fallback: bool,
) -> dict | None:
    """校验 Adapter API token，并可要求数据库 scope。"""
    expected = os.getenv("ADAPTER_API_TOKEN")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        if allow_env_fallback and not expected and not db.configured():
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
        scopes = set(api_client.get("scopes") or [])
        if required_scope and required_scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token missing required scope: {required_scope}",
            )
        return api_client

    if allow_env_fallback and expected and hmac.compare_digest(token, expected):
        return

    if allow_env_fallback and not expected and not db.configured():
        return

    if db_lookup_failed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API token store unavailable",
        )

    if required_scope and expected and hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token missing required scope: {required_scope}",
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
