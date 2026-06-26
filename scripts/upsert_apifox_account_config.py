"""
Upsert Adapter Apifox account token config into MySQL.

Example:
  APIFOX_ACCESS_TOKEN='<不要写入文档或聊天>' \
  python scripts/upsert_apifox_account_config.py ^
    --account-name apifox-main ^
    --remark 主Apifox账号

The script reads DB connection settings from environment variables and never
prints secrets.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-name", required=True, help="Apifox账号配置名称，例如 apifox-main")
    parser.add_argument("--access-token", default=os.getenv("APIFOX_ACCESS_TOKEN") or "", help="Apifox Access Token")
    parser.add_argument("--disabled", action="store_true", help="写入为停用状态")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not args.access_token:
        raise SystemExit("Apifox access token is missing; set APIFOX_ACCESS_TOKEN or --access-token")
    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_apifox_account_config (
                    account_name,
                    access_token,
                    enabled,
                    remark
                )
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    access_token = VALUES(access_token),
                    enabled = VALUES(enabled),
                    remark = VALUES(remark)
                """,
                (
                    args.account_name,
                    args.access_token,
                    0 if args.disabled else 1,
                    args.remark or None,
                ),
            )

    enabled_text = "false" if args.disabled else "true"
    print(f"apifox account config upserted: accountName={args.account_name}, enabled={enabled_text}")


if __name__ == "__main__":
    main()
