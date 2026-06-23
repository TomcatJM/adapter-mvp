"""
Upsert Adapter Apifox project mapping into MySQL.

Example:
  python scripts/upsert_apifox_project_config.py ^
    --project-name jdb-order ^
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
    parser.add_argument("--apifox-project-id", required=True, help="Apifox 项目 ID，例如 7049238")
    parser.add_argument("--openapi-url", default="", help="项目专属 OpenAPI JSON/YAML 直链")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_apifox_project_config (project_name, apifox_project_id, openapi_url, remark)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    apifox_project_id = VALUES(apifox_project_id),
                    openapi_url = VALUES(openapi_url),
                    remark = VALUES(remark)
                """,
                (args.project_name, args.apifox_project_id, args.openapi_url or None, args.remark or None),
            )

    print(
        "apifox project config upserted: "
        f"projectName={args.project_name}, apifoxProjectId={args.apifox_project_id}"
    )


if __name__ == "__main__":
    main()
