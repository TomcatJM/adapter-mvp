#!/usr/bin/env python3
"""
Read DingTalk/Alidocs content through Adapter-managed DingTalk OpenAPI calls.

This script is the Codex-friendly entry point for alidocs.dingtalk.com links.
It never prints tokens/cookies and reads a narrow spreadsheet range by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.dingtalk_docs import DingTalkDocError, read_dingtalk_doc  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="DingTalk/Alidocs URL")
    parser.add_argument("--node", dest="node_id", help="DingTalk/Alidocs node id")
    parser.add_argument("--config-name", help="DingTalk app config name")
    parser.add_argument("--kind", choices=["adoc", "axls", "document", "sheet"], help="Document kind")
    parser.add_argument("--sheet-id", help="Sheet id for axls docs")
    parser.add_argument("--range", default="A1:J50", help="Sheet range for axls docs")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()

    try:
        result = read_dingtalk_doc(
            url=args.url,
            node_id=args.node_id,
            sheet_id=args.sheet_id,
            cell_range=args.range,
            timeout=args.timeout,
            config_name=args.config_name,
            kind=args.kind,
        )
    except DingTalkDocError as exc:
        raise SystemExit(f"failed to read DingTalk doc: {exc}") from exc

    if args.format == "text":
        print(_to_text(result))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _to_text(result: dict[str, Any]) -> str:
    lines = [
        f"nodeId: {result.get('nodeId')}",
        f"extension: {result.get('extension')}",
        f"kind: {result.get('kind')}",
    ]
    if result.get("kind") == "sheet":
        lines.append(f"sheetId: {result.get('sheetId')}")
        lines.append(f"range: {result.get('range')}")
        lines.append(json.dumps(result.get("rangeResult"), ensure_ascii=False, indent=2))
    else:
        lines.append(json.dumps(result.get("document"), ensure_ascii=False, indent=2))
    return "\n".join(lines)


if __name__ == "__main__":
    main()
