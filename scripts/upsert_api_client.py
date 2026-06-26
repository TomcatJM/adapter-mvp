#!/usr/bin/env python3
"""
Upsert Adapter API client token into MySQL.

Prefer environment variables so tokens do not land in shell history:
  ADAPTER_CLIENT_TOKEN=xxx python scripts/upsert_api_client.py \
    --client-id codex-local \
    --client-name Codex本地调用 \
    --scopes workflow:read,workflow:write \
    --created-by 姬志猛

The script stores SHA-256 token hashes and the original token in MySQL, but
never prints the token.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True, help="调用方 ID，例如 codex-local、yunxiao-flow")
    parser.add_argument("--client-name", required=True, help="调用方名称")
    parser.add_argument("--token", help="API token 明文；推荐改用 ADAPTER_CLIENT_TOKEN，避免进入 shell 历史")
    parser.add_argument("--token-env", default="ADAPTER_CLIENT_TOKEN", help="读取 token 的环境变量名")
    parser.add_argument("--scopes", default="", help="权限范围，逗号分隔，例如 workflow:read,workflow:write")
    parser.add_argument("--enabled", choices=("0", "1"), default="1", help="是否启用：1启用，0停用")
    parser.add_argument("--expires-at", default=None, help="过期时间，例如 2026-12-31 23:59:59；空表示不过期")
    parser.add_argument("--created-by", default="", help="创建人")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    token = args.token or os.getenv(args.token_env)
    if not token:
        token = getpass.getpass(f"Input token for {args.client_id}: ")
    token = token.strip()
    if not token:
        raise SystemExit("Adapter API client token is missing")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_api_client (
                    client_id,
                    client_name,
                    token_hash,
                    token_plaintext,
                    scopes,
                    enabled,
                    expires_at,
                    created_by,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    client_name = VALUES(client_name),
                    token_hash = VALUES(token_hash),
                    token_plaintext = VALUES(token_plaintext),
                    scopes = VALUES(scopes),
                    enabled = VALUES(enabled),
                    expires_at = VALUES(expires_at),
                    created_by = VALUES(created_by),
                    remark = VALUES(remark)
                """,
                (
                    args.client_id,
                    args.client_name,
                    db.hash_api_token(token),
                    token,
                    args.scopes or None,
                    int(args.enabled),
                    args.expires_at or None,
                    args.created_by or None,
                    args.remark or None,
                ),
            )

    print(f"adapter api client upserted: clientId={args.client_id}, enabled={args.enabled}")


if __name__ == "__main__":
    main()
