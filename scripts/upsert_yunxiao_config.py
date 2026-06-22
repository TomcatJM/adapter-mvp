#!/usr/bin/env python3
"""
Upsert Adapter Yunxiao account and project mapping into MySQL.

Prefer environment variables for AK secrets so they do not land in shell history:
  ALIBABA_CLOUD_ACCESS_KEY_ID=xxx ALIBABA_CLOUD_ACCESS_KEY_SECRET=yyy \
    python scripts/upsert_yunxiao_config.py \
      --project-name jdb-school-crm \
      --organization-id org-id \
      --project-id space-id \
      --workitem-type-identifier type-id \
      --default-assignee user-id \
      --member-name 姬志猛 \
      --member-account-id user-id \
      --member-default \
      --done-status-id done-status-id

Legacy CLI token configs can be imported explicitly:
  python scripts/upsert_yunxiao_config.py --auth-type legacy_token \
    --legacy-config /root/.openclaw/yunxiao-task-config.json \
    --project-name jdb-school-crm --project-id space-id --default-assignee user-id

Project members can also be maintained without touching account/project config:
  python scripts/upsert_yunxiao_config.py --member-only \
    --project-name jdb-school-crm \
    --member-name 姬志猛 \
    --member-account-id user-id \
    --member-default

The script reads DB connection settings from environment variables and never
prints AccessKey values, legacy tokens, security tokens, or other secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-name", default=os.getenv("YUNXIAO_ACCOUNT_NAME") or "default")
    parser.add_argument(
        "--auth-type",
        choices=("acs_ak", "legacy_token"),
        default=os.getenv("YUNXIAO_AUTH_TYPE") or "acs_ak",
    )
    parser.add_argument("--access-key-id", default=os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID") or os.getenv("ALIYUN_ACCESS_KEY_ID"))
    parser.add_argument(
        "--access-key-secret",
        default=os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or os.getenv("ALIYUN_ACCESS_KEY_SECRET"),
    )
    parser.add_argument("--legacy-token", default=os.getenv("YUNXIAO_TOKEN") or os.getenv("YUNXIAO_LEGACY_TOKEN"))
    parser.add_argument("--legacy-config", help="旧CLI配置JSON，例如 /root/.openclaw/yunxiao-task-config.json")
    parser.add_argument("--security-token", default=os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN") or os.getenv("ALIYUN_SECURITY_TOKEN"))
    parser.add_argument("--endpoint", default=os.getenv("YUNXIAO_OPENAPI_ENDPOINT") or "devops.cn-hangzhou.aliyuncs.com")
    parser.add_argument("--project-name", required=True, help="业务项目名称，例如 jdb-school-crm")
    parser.add_argument("--organization-id", help="云效企业/组织 ID")
    parser.add_argument("--project-id", help="云效项目 ID 或 spaceIdentifier")
    parser.add_argument("--sprint-id", help="云效迭代 ID，旧接口可选")
    parser.add_argument("--workitem-category", default="Req", help="云效工作项分类，例如 Req")
    parser.add_argument("--workitem-type-identifier", help="云效工作项类型 ID")
    parser.add_argument("--default-assignee", help="兼容字段：项目表默认负责人云效账号 ID")
    parser.add_argument("--member-name", help="项目人员姓名，例如 姬志猛")
    parser.add_argument("--member-account-id", help="项目人员云效账号 ID")
    parser.add_argument(
        "--member-default",
        action="store_true",
        help="将本次 member 设置为项目默认负责人；会取消同项目其他默认负责人",
    )
    parser.add_argument("--priority-field-id")
    parser.add_argument("--priority-default-value")
    parser.add_argument("--participants", help="参与人，逗号分隔")
    parser.add_argument("--trackers", help="关注人，逗号分隔")
    parser.add_argument("--verifier", help="验证人云效账号 ID")
    parser.add_argument("--done-status-id", default=os.getenv("YUNXIAO_DONE_STATUS_ID"), help="云效完成状态 ID")
    parser.add_argument(
        "--done-status-field-id",
        default=os.getenv("YUNXIAO_DONE_STATUS_FIELD_ID") or "status",
        help="云效状态字段 ID，默认 status",
    )
    parser.add_argument(
        "--done-status-names",
        default=os.getenv("YUNXIAO_DONE_STATUS_NAMES"),
        help="已完成状态名称，逗号分隔，用于幂等判断",
    )
    parser.add_argument(
        "--comment-field-key",
        default=os.getenv("YUNXIAO_COMMENT_FIELD_KEY") or os.getenv("YUNXIAO_WRITEBACK_FIELD"),
        help="回写字段 Key，保留扩展",
    )
    parser.add_argument(
        "--comment-format-type",
        default=os.getenv("YUNXIAO_COMMENT_FORMAT_TYPE") or "MARKDOWN",
        help="评论格式，默认 MARKDOWN",
    )
    parser.add_argument(
        "--close-transition-id",
        default=os.getenv("YUNXIAO_CLOSE_TRANSITION_ID"),
        help="云效关闭流转 ID；配置后优先于 done-status-id",
    )
    parser.add_argument("--remark", default="")
    parser.add_argument(
        "--skip-account",
        action="store_true",
        help="只写项目映射，要求 adapter_yunxiao_account_config 中已存在 account-name",
    )
    parser.add_argument(
        "--member-only",
        action="store_true",
        help="只维护 adapter_yunxiao_project_member，不修改账号或项目映射",
    )
    args = parser.parse_args()

    legacy_config = _read_legacy_config(args.legacy_config)
    if legacy_config:
        args.legacy_token = args.legacy_token or legacy_config.get("token")
        args.endpoint = legacy_config.get("endpoint") or args.endpoint
        args.organization_id = args.organization_id or legacy_config.get("orgId")
        args.workitem_type_identifier = args.workitem_type_identifier or legacy_config.get("workitemTypeId")

    if not db.configured():
        raise SystemExit("Database env is not configured")
    if not args.account_name:
        raise SystemExit("Yunxiao account name is missing")
    if args.member_only and (not args.member_name or not args.member_account_id):
        raise SystemExit("Set --member-name and --member-account-id when --member-only is used")
    if not args.member_only and not args.project_id:
        raise SystemExit("Yunxiao project id is missing; set --project-id")
    if not args.member_only and not args.skip_account and args.auth_type == "acs_ak" and not args.access_key_id:
        raise SystemExit("Yunxiao access key id is missing; set ALIBABA_CLOUD_ACCESS_KEY_ID or --access-key-id")
    if not args.member_only and not args.skip_account and args.auth_type == "acs_ak" and not args.access_key_secret:
        raise SystemExit(
            "Yunxiao access key secret is missing; set ALIBABA_CLOUD_ACCESS_KEY_SECRET or --access-key-secret"
        )
    if not args.member_only and not args.skip_account and args.auth_type == "legacy_token" and not args.legacy_token:
        raise SystemExit("Yunxiao legacy token is missing; set YUNXIAO_TOKEN, --legacy-token, or --legacy-config")
    if not args.member_only and not args.organization_id:
        raise SystemExit("Yunxiao organization id is missing; set --organization-id or --legacy-config")
    if not args.member_only and not args.workitem_type_identifier:
        raise SystemExit(
            "Yunxiao workitem type identifier is missing; set --workitem-type-identifier or --legacy-config"
        )
    if bool(args.member_name) != bool(args.member_account_id):
        raise SystemExit("Set --member-name and --member-account-id together")
    if not args.member_only and not args.default_assignee and args.member_default and args.member_account_id:
        args.default_assignee = args.member_account_id
    if not args.member_only and not args.default_assignee:
        raise SystemExit("Yunxiao default assignee is missing; set --default-assignee or --member-default with member")

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            if not args.member_only and not args.skip_account:
                cursor.execute(
                    """
                    INSERT INTO adapter_yunxiao_account_config (
                        account_name,
                        auth_type,
                        access_key_id,
                        access_key_secret,
                        legacy_token,
                        security_token,
                        endpoint,
                        remark
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        auth_type = VALUES(auth_type),
                        access_key_id = VALUES(access_key_id),
                        access_key_secret = VALUES(access_key_secret),
                        legacy_token = VALUES(legacy_token),
                        security_token = VALUES(security_token),
                        endpoint = VALUES(endpoint),
                        remark = VALUES(remark)
                    """,
                    (
                        args.account_name,
                        args.auth_type,
                        args.access_key_id if args.auth_type == "acs_ak" else None,
                        args.access_key_secret if args.auth_type == "acs_ak" else None,
                        args.legacy_token if args.auth_type == "legacy_token" else None,
                        args.security_token or None,
                        args.endpoint,
                        args.remark or None,
                    ),
                )
            if not args.member_only:
                cursor.execute(
                    """
                    INSERT INTO adapter_yunxiao_project_config (
                        project_name,
                        account_name,
                        organization_id,
                        project_id,
                        sprint_id,
                        workitem_category,
                        workitem_type_identifier,
                        default_assignee,
                        priority_field_id,
                        priority_default_value,
                        participants,
                        trackers,
                        verifier,
                        done_status_id,
                        done_status_field_id,
                        done_status_names,
                        comment_field_key,
                        comment_format_type,
                        close_transition_id,
                        remark
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        account_name = VALUES(account_name),
                        organization_id = VALUES(organization_id),
                        project_id = VALUES(project_id),
                        sprint_id = VALUES(sprint_id),
                        workitem_category = VALUES(workitem_category),
                        workitem_type_identifier = VALUES(workitem_type_identifier),
                        default_assignee = VALUES(default_assignee),
                        priority_field_id = VALUES(priority_field_id),
                        priority_default_value = VALUES(priority_default_value),
                        participants = VALUES(participants),
                        trackers = VALUES(trackers),
                        verifier = VALUES(verifier),
                        done_status_id = VALUES(done_status_id),
                        done_status_field_id = VALUES(done_status_field_id),
                        done_status_names = VALUES(done_status_names),
                        comment_field_key = VALUES(comment_field_key),
                        comment_format_type = VALUES(comment_format_type),
                        close_transition_id = VALUES(close_transition_id),
                        remark = VALUES(remark)
                    """,
                    (
                        args.project_name,
                        args.account_name,
                        args.organization_id,
                        args.project_id,
                        args.sprint_id,
                        args.workitem_category,
                        args.workitem_type_identifier,
                        args.default_assignee,
                        args.priority_field_id,
                        args.priority_default_value,
                        args.participants,
                        args.trackers,
                        args.verifier,
                        args.done_status_id,
                        args.done_status_field_id,
                        args.done_status_names,
                        args.comment_field_key,
                        args.comment_format_type,
                        args.close_transition_id,
                        args.remark or None,
                    ),
                )
            if args.member_name and args.member_account_id:
                if args.member_default:
                    cursor.execute(
                        """
                        UPDATE adapter_yunxiao_project_member
                        SET is_default = 0
                        WHERE LOWER(project_name) = LOWER(%s)
                        """,
                        (args.project_name,),
                    )
                cursor.execute(
                    """
                    INSERT INTO adapter_yunxiao_project_member (
                        project_name,
                        member_name,
                        yunxiao_account_id,
                        is_default,
                        enabled,
                        remark
                    )
                    VALUES (%s, %s, %s, %s, 1, %s)
                    ON DUPLICATE KEY UPDATE
                        member_name = VALUES(member_name),
                        yunxiao_account_id = VALUES(yunxiao_account_id),
                        is_default = VALUES(is_default),
                        enabled = 1,
                        remark = VALUES(remark)
                    """,
                    (
                        args.project_name,
                        args.member_name,
                        args.member_account_id,
                        1 if args.member_default else 0,
                        args.remark or None,
                    ),
                )

    if args.member_only:
        default_text = "true" if args.member_default else "false"
        print(
            "yunxiao member upserted: "
            f"projectName={args.project_name}, memberName={args.member_name}, isDefault={default_text}"
        )
        return

    print(
        "yunxiao config upserted: "
        f"accountName={args.account_name}, authType={args.auth_type}, "
        f"projectName={args.project_name}, projectId={args.project_id}"
    )


def _read_legacy_config(path: str | None) -> dict:
    if not path:
        return {}
    expanded = Path(path).expanduser()
    if not expanded.exists():
        raise SystemExit(f"Legacy Yunxiao config not found: {expanded}")
    with expanded.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise SystemExit(f"Legacy Yunxiao config must be a JSON object: {expanded}")
    return data


if __name__ == "__main__":
    main()
