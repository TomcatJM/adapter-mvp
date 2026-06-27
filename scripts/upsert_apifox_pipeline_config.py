"""
Upsert Adapter Apifox pipeline-to-project mapping into MySQL.

Example:
  python scripts/upsert_apifox_pipeline_config.py ^
    --pipeline-id 4989239 ^
    --pipeline-name jdb-school-gmc开发/UAT部署 ^
    --service-name jdb-school-gmc ^
    --env-name dev-uat ^
    --apifox-project-config-id 12 ^
    --remark 订单服务Kubernetes发布流水线

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
    parser.add_argument("--pipeline-id", required=True, help="云效流水线 ID，例如 4989239")
    parser.add_argument("--apifox-project-config-id", required=True, type=int, help="Apifox项目配置主键ID")
    parser.add_argument("--service-name", required=True, help="服务名，例如 jdb-school-gmc")
    parser.add_argument("--env-name", required=True, help="环境名，例如 dev-uat")
    parser.add_argument("--pipeline-name", default="", help="云效流水线名称，例如 jdb-school-gmc开发/UAT部署")
    parser.add_argument("--repo-name", default="", help="仓库名，例如 jdb-school-gmc")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            _assert_apifox_project_config_exists(cursor, args.apifox_project_config_id)
            cursor.execute(
                """
                INSERT INTO adapter_apifox_pipeline_config (
                    pipeline_id,
                    pipeline_name,
                    service_name,
                    env_name,
                    repo_name,
                    apifox_project_config_id,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    pipeline_name = VALUES(pipeline_name),
                    service_name = VALUES(service_name),
                    env_name = VALUES(env_name),
                    repo_name = VALUES(repo_name),
                    apifox_project_config_id = VALUES(apifox_project_config_id),
                    remark = VALUES(remark)
                """,
                (
                    args.pipeline_id,
                    args.pipeline_name or None,
                    args.service_name,
                    args.env_name,
                    args.repo_name or None,
                    args.apifox_project_config_id,
                    args.remark or None,
                ),
            )

    print(
        "apifox pipeline config upserted: "
        f"pipelineId={args.pipeline_id}, serviceName={args.service_name}, envName={args.env_name}, "
        f"apifoxProjectConfigId={args.apifox_project_config_id}"
    )


def _assert_apifox_project_config_exists(cursor, config_id: int) -> None:
    cursor.execute(
        """
        SELECT id
        FROM adapter_apifox_project_config
        WHERE id = %s
        LIMIT 1
        """,
        (config_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise SystemExit(f"Apifox project config not found: id={config_id}")


if __name__ == "__main__":
    main()
