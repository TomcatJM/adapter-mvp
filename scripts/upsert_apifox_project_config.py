"""
Upsert Adapter Apifox project mapping into MySQL.

Example:
  python scripts/upsert_apifox_project_config.py ^
    --project-name jdb-order ^
    --account-name apifox-main ^
    --apifox-project-id 7049238 ^
    --openapi-url https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs ^
    --remark 订单服务接口项目-流水线重新导入目标

The script reads DB connection settings from environment variables and never
prints secrets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True, help="项目名称，例如 jdb-order")
    parser.add_argument("--account-name", default="", help="Apifox账号配置名称，例如 apifox-main")
    parser.add_argument("--apifox-project-id", required=True, help="Apifox 项目 ID，例如 7049238")
    parser.add_argument("--openapi-url", default="", help="项目专属 OpenAPI JSON/YAML 直链")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            account_config_id = _find_id_by_name(
                cursor,
                table="adapter_apifox_account_config",
                name_column="account_name",
                name_value=args.account_name,
            )
            cursor.execute(
                """
                INSERT INTO adapter_apifox_project_config (
                    project_name,
                    account_name,
                    account_config_id,
                    apifox_project_id,
                    openapi_url,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    account_name = COALESCE(VALUES(account_name), account_name),
                    account_config_id = COALESCE(VALUES(account_config_id), account_config_id),
                    apifox_project_id = VALUES(apifox_project_id),
                    openapi_url = VALUES(openapi_url),
                    remark = VALUES(remark)
                """,
                (
                    args.project_name,
                    args.account_name or None,
                    account_config_id,
                    args.apifox_project_id,
                    args.openapi_url or None,
                    args.remark or None,
                ),
            )

    print(
        "apifox project config upserted: "
        f"projectName={args.project_name}, apifoxProjectId={args.apifox_project_id}"
    )


def _find_id_by_name(cursor, *, table: str, name_column: str, name_value: str | None) -> int | None:
    if not name_value:
        return None
    if table not in {"adapter_apifox_account_config"}:
        raise ValueError(f"Unsupported table for id lookup: {table}")
    if name_column not in {"account_name"}:
        raise ValueError(f"Unsupported column for id lookup: {name_column}")
    cursor.execute(
        f"""
        SELECT id
        FROM {table}
        WHERE LOWER({name_column}) = LOWER(%s)
        LIMIT 1
        """,
        (name_value,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row.get("id")


if __name__ == "__main__":
    main()
