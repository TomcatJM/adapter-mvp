"""
Upsert Adapter Apifox pipeline-to-project mapping into MySQL.

Example:
  python scripts/upsert_apifox_pipeline_config.py ^
    --pipeline-id 4989239 ^
    --project-name jdb-order ^
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
    parser.add_argument("--project-name", required=True, help="项目名称，例如 jdb-order")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_apifox_pipeline_config (pipeline_id, project_name, remark)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    project_name = VALUES(project_name),
                    remark = VALUES(remark)
                """,
                (args.pipeline_id, args.project_name, args.remark or None),
            )

    print(
        "apifox pipeline config upserted: "
        f"pipelineId={args.pipeline_id}, projectName={args.project_name}"
    )


if __name__ == "__main__":
    main()
