"""
Upsert Adapter project configuration into MySQL.

Example:
  python scripts/upsert_adapter_project_config.py ^
    --project-key jdb-school-crm ^
    --project-name 校CRM ^
    --knowledge-endpoint http://127.0.0.1:8080/white/KnowledgeGraph/query ^
    --codegraph-enabled ^
    --oss-bucket ai-dev-artifacts ^
    --oss-prefix codegraph/jdb-school-crm ^
    --remark 校CRM一期知识上下文接入
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
    parser.add_argument("--project-key", required=True, help="项目唯一Key，例如 jdb-school-crm")
    parser.add_argument("--project-name", required=True, help="项目展示名称，例如 校CRM")
    parser.add_argument("--knowledge-endpoint", default="", help="项目知识图谱查询接口")
    parser.add_argument("--codegraph-enabled", action="store_true", help="启用CodeGraph索引")
    parser.add_argument("--codegraph-strategy", default="oss-artifact", help="CodeGraph策略")
    parser.add_argument("--oss-bucket", default="", help="CodeGraph索引所在OSS bucket")
    parser.add_argument("--oss-prefix", default="", help="CodeGraph索引OSS前缀")
    parser.add_argument("--remark", default="", help="备注")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")

    db.upsert_adapter_project_config(
        project_key=args.project_key,
        project_name=args.project_name,
        knowledge_endpoint=args.knowledge_endpoint or None,
        codegraph_enabled=args.codegraph_enabled,
        codegraph_strategy=args.codegraph_strategy,
        oss_bucket=args.oss_bucket or None,
        oss_prefix=args.oss_prefix or None,
        remark=args.remark or None,
    )

    print(f"adapter project config upserted: projectKey={args.project_key}, projectName={args.project_name}")


if __name__ == "__main__":
    main()
