#!/usr/bin/env python3
"""
Upsert Adapter DingTalk app and document-read configuration into MySQL.

Prefer environment variables for secrets so they do not land in shell history:
  DINGTALK_APP_KEY=xxx DINGTALK_APP_SECRET=yyy python scripts/upsert_dingtalk_config.py --config-name default

The script reads DB connection settings from environment variables and never
prints appKey, appSecret, or access tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-name", default="default")
    parser.add_argument("--app-name", default=os.getenv("DINGTALK_APP_NAME") or "JDB小钉")
    parser.add_argument("--app-key", default=os.getenv("DINGTALK_APP_KEY"))
    parser.add_argument("--app-secret", default=os.getenv("DINGTALK_APP_SECRET"))
    parser.add_argument("--auth-endpoint", default="https://api.dingtalk.com/v1.0/oauth2/accessToken")
    parser.add_argument("--token-header-name", default="x-acs-dingtalk-access-token")
    parser.add_argument("--operator-id", default=os.getenv("DINGTALK_OPERATOR_ID"))
    parser.add_argument("--doc-info-method", default="GET")
    parser.add_argument("--doc-info-url-template")
    parser.add_argument("--doc-info-body-template")
    parser.add_argument("--doc-read-method", default="GET")
    parser.add_argument("--doc-read-url-template")
    parser.add_argument("--doc-read-body-template")
    parser.add_argument("--sheet-list-method", default="GET")
    parser.add_argument("--sheet-list-url-template")
    parser.add_argument("--sheet-list-body-template")
    parser.add_argument("--sheet-range-method", default="GET")
    parser.add_argument("--sheet-range-url-template")
    parser.add_argument("--sheet-range-body-template")
    parser.add_argument("--remark", default="")
    args = parser.parse_args()

    if not db.configured():
        raise SystemExit("Database env is not configured")
    if not args.app_name:
        raise SystemExit("DingTalk app name is missing; set DINGTALK_APP_NAME or --app-name")
    if not args.app_key:
        raise SystemExit("DingTalk app key is missing; set DINGTALK_APP_KEY or --app-key")
    if not args.app_secret:
        raise SystemExit("DingTalk app secret is missing; set DINGTALK_APP_SECRET or --app-secret")

    app_values = (
        args.app_name,
        args.app_key,
        args.app_secret,
        args.auth_endpoint,
        args.token_header_name,
        args.remark or None,
    )
    doc_values = (
        args.config_name,
        args.app_name,
        args.operator_id,
        args.doc_info_method.upper(),
        args.doc_info_url_template,
        _json_text(args.doc_info_body_template),
        args.doc_read_method.upper(),
        args.doc_read_url_template,
        _json_text(args.doc_read_body_template),
        args.sheet_list_method.upper(),
        args.sheet_list_url_template,
        _json_text(args.sheet_list_body_template),
        args.sheet_range_method.upper(),
        args.sheet_range_url_template,
        _json_text(args.sheet_range_body_template),
        args.remark or None,
    )

    db.ensure_schema()
    with db.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_dingtalk_app (
                    app_name,
                    app_key,
                    app_secret,
                    auth_endpoint,
                    token_header_name,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    access_token = CASE
                        WHEN app_key <> VALUES(app_key)
                          OR app_secret <> VALUES(app_secret)
                          OR auth_endpoint <> VALUES(auth_endpoint)
                        THEN NULL
                        ELSE access_token
                    END,
                    token_expires_at = CASE
                        WHEN app_key <> VALUES(app_key)
                          OR app_secret <> VALUES(app_secret)
                          OR auth_endpoint <> VALUES(auth_endpoint)
                        THEN NULL
                        ELSE token_expires_at
                    END,
                    app_key = VALUES(app_key),
                    app_secret = VALUES(app_secret),
                    auth_endpoint = VALUES(auth_endpoint),
                    token_header_name = VALUES(token_header_name),
                    remark = VALUES(remark)
                """,
                app_values,
            )
            cursor.execute(
                """
                INSERT INTO adapter_dingtalk_doc_config (
                    config_name,
                    app_name,
                    operator_id,
                    doc_info_method,
                    doc_info_url_template,
                    doc_info_body_template,
                    doc_read_method,
                    doc_read_url_template,
                    doc_read_body_template,
                    sheet_list_method,
                    sheet_list_url_template,
                    sheet_list_body_template,
                    sheet_range_method,
                    sheet_range_url_template,
                    sheet_range_body_template,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    app_name = VALUES(app_name),
                    operator_id = VALUES(operator_id),
                    doc_info_method = VALUES(doc_info_method),
                    doc_info_url_template = VALUES(doc_info_url_template),
                    doc_info_body_template = VALUES(doc_info_body_template),
                    doc_read_method = VALUES(doc_read_method),
                    doc_read_url_template = VALUES(doc_read_url_template),
                    doc_read_body_template = VALUES(doc_read_body_template),
                    sheet_list_method = VALUES(sheet_list_method),
                    sheet_list_url_template = VALUES(sheet_list_url_template),
                    sheet_list_body_template = VALUES(sheet_list_body_template),
                    sheet_range_method = VALUES(sheet_range_method),
                    sheet_range_url_template = VALUES(sheet_range_url_template),
                    sheet_range_body_template = VALUES(sheet_range_body_template),
                    remark = VALUES(remark)
                """,
                doc_values,
            )
            cursor.execute(
                """
                INSERT INTO adapter_dingtalk_app_config (
                    config_name,
                    app_key,
                    app_secret,
                    auth_endpoint,
                    token_header_name,
                    operator_id,
                    doc_info_method,
                    doc_info_url_template,
                    doc_info_body_template,
                    doc_read_method,
                    doc_read_url_template,
                    doc_read_body_template,
                    sheet_list_method,
                    sheet_list_url_template,
                    sheet_list_body_template,
                    sheet_range_method,
                    sheet_range_url_template,
                    sheet_range_body_template,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    app_key = VALUES(app_key),
                    app_secret = VALUES(app_secret),
                    auth_endpoint = VALUES(auth_endpoint),
                    token_header_name = VALUES(token_header_name),
                    operator_id = VALUES(operator_id),
                    doc_info_method = VALUES(doc_info_method),
                    doc_info_url_template = VALUES(doc_info_url_template),
                    doc_info_body_template = VALUES(doc_info_body_template),
                    doc_read_method = VALUES(doc_read_method),
                    doc_read_url_template = VALUES(doc_read_url_template),
                    doc_read_body_template = VALUES(doc_read_body_template),
                    sheet_list_method = VALUES(sheet_list_method),
                    sheet_list_url_template = VALUES(sheet_list_url_template),
                    sheet_list_body_template = VALUES(sheet_list_body_template),
                    sheet_range_method = VALUES(sheet_range_method),
                    sheet_range_url_template = VALUES(sheet_range_url_template),
                    sheet_range_body_template = VALUES(sheet_range_body_template),
                    access_token = NULL,
                    token_expires_at = NULL,
                    remark = VALUES(remark)
                """,
                (
                    args.config_name,
                    args.app_key,
                    args.app_secret,
                    args.auth_endpoint,
                    args.token_header_name,
                    args.operator_id,
                    args.doc_info_method.upper(),
                    args.doc_info_url_template,
                    _json_text(args.doc_info_body_template),
                    args.doc_read_method.upper(),
                    args.doc_read_url_template,
                    _json_text(args.doc_read_body_template),
                    args.sheet_list_method.upper(),
                    args.sheet_list_url_template,
                    _json_text(args.sheet_list_body_template),
                    args.sheet_range_method.upper(),
                    args.sheet_range_url_template,
                    _json_text(args.sheet_range_body_template),
                    args.app_name,
                ),
            )

    print(f"dingtalk config upserted: configName={args.config_name}, appName={args.app_name}")


def _json_text(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    parsed: Any = json.loads(value)
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
