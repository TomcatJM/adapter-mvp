#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.yunxiao_guard import YunxiaoWorkflowGuardError, load_workflow_json, validate_workflow


def main() -> int:
    """执行云效 workflow 离线强校验。"""
    parser = argparse.ArgumentParser(description="Validate Adapter MVP Yunxiao workflow guard rules.")
    parser.add_argument("--file", help="workflow JSON 文件路径；不传则从 stdin 读取")
    parser.add_argument("--mode", choices=["all", "create-result", "close-plan"], default="all")
    args = parser.parse_args()

    try:
        workflow = load_workflow_json(args.file) if args.file else _read_stdin_json()
        checks = validate_workflow(workflow, mode=args.mode)
    except (json.JSONDecodeError, OSError, YunxiaoWorkflowGuardError) as exc:
        print(f"guard failed: {exc}", file=sys.stderr)
        return 1

    print("guard passed: " + ",".join(checks))
    return 0


def _read_stdin_json() -> dict:
    data = json.loads(sys.stdin.read())
    if not isinstance(data, dict):
        raise YunxiaoWorkflowGuardError("Workflow JSON must be an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
