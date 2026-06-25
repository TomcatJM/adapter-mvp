import os
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
PERMISSIONS_PATH = ROOT / "config" / "permissions.yaml"


def load_permissions() -> dict[str, Any]:
    """加载权限配置。"""
    if not PERMISSIONS_PATH.exists():
        return {}
    with PERMISSIONS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def action_policy(system: str, action: str, env: str) -> dict[str, Any]:
    """获取动作策略。"""
    permissions = load_permissions()
    defaults = permissions.get("defaults", {})
    action_cfg = (
        permissions.get("actions", {})
        .get(system, {})
        .get(action, {})
        .get(env, {})
    )
    return {**defaults, **action_cfg}


def remote_execution_enabled() -> bool:
    """判断是否允许远端执行。"""
    return os.getenv("ALLOW_REMOTE_EXEC", "false").lower() == "true"

