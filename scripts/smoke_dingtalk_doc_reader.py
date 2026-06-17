"""
Smoke-test DingTalk doc reader parsing and adoc/axls branching without network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.dingtalk_docs as docs  # noqa: E402


def main() -> None:
    original_find = docs.db.find_dingtalk_app_config
    original_update = docs.db.update_dingtalk_token_cache
    original_request = docs._request_json
    try:
        calls: list[tuple[str, str]] = []

        def fake_find(config_name: str) -> dict[str, Any]:
            return {
                "configName": config_name,
                "appKey": "fake-key",
                "appSecret": "fake-secret",
                "authEndpoint": "https://example.invalid/token",
                "tokenHeaderName": "x-acs-dingtalk-access-token",
                "operatorId": "manager123",
                "doc_infoMethod": "GET",
                "doc_infoUrlTemplate": "https://example.invalid/doc/{nodeId}",
                "doc_infoBodyTemplate": None,
                "doc_readMethod": "GET",
                "doc_readUrlTemplate": "https://example.invalid/doc/{nodeId}/content",
                "doc_readBodyTemplate": None,
                "sheet_listMethod": "GET",
                "sheet_listUrlTemplate": "https://example.invalid/sheets/{nodeId}",
                "sheet_listBodyTemplate": None,
                "sheet_rangeMethod": "POST",
                "sheet_rangeUrlTemplate": "https://example.invalid/sheets/{nodeId}/range?operatorId={operatorId}",
                "sheet_rangeBodyTemplate": {"sheetId": "{sheetId}", "range": "{range}"},
                "accessToken": "cached-token",
                "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(hours=1),
            }

        def fake_update(config_name: str, access_token: str, token_expires_at: datetime) -> None:
            raise AssertionError("cached token should be reused")

        def fake_request(method: str, url: str, payload: Any, headers: dict[str, str], timeout: int) -> Any:
            calls.append((method, url))
            assert headers.get("x-acs-dingtalk-access-token") == "cached-token"
            if url.endswith("/doc/adoc-node"):
                return {"extension": "adoc", "title": "接口文档"}
            if url.endswith("/doc/adoc-node/content"):
                return {"text": "POST /demo 接口说明"}
            if url.endswith("/doc/sheet-node"):
                return {"data": {"extension": "axls", "title": "接口表"}}
            if url.endswith("/sheets/sheet-node"):
                return {"sheets": [{"sheetId": "sid-1", "name": "接口"}]}
            if url.endswith("/sheets/sheet-node/range?operatorId=manager123"):
                assert payload == {"sheetId": "sid-1", "range": "A1:J50"}
                return {"values": [["path", "method"], ["/demo", "POST"]]}
            raise AssertionError(url)

        docs.db.find_dingtalk_app_config = fake_find  # type: ignore[method-assign]
        docs.db.update_dingtalk_token_cache = fake_update  # type: ignore[method-assign]
        docs._request_json = fake_request  # type: ignore[assignment]

        adoc = docs.read_dingtalk_doc(url="https://alidocs.dingtalk.com/i/nodes/adoc-node?x=1")
        assert adoc["kind"] == "document", adoc
        assert adoc["document"]["text"] == "POST /demo 接口说明", adoc

        sheet = docs.read_dingtalk_doc(node_id="sheet-node")
        assert sheet["kind"] == "sheet", sheet
        assert sheet["metadata"]["title"] == "接口表", sheet
        assert sheet["sheetId"] == "sid-1", sheet
        assert sheet["rangeResult"]["values"][1] == ["/demo", "POST"], sheet
        assert len(calls) == 5, calls
        print("dingtalk doc reader smoke OK")
    finally:
        docs.db.find_dingtalk_app_config = original_find  # type: ignore[method-assign]
        docs.db.update_dingtalk_token_cache = original_update  # type: ignore[method-assign]
        docs._request_json = original_request  # type: ignore[assignment]


if __name__ == "__main__":
    main()
