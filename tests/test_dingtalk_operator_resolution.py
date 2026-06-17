import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.dingtalk_docs import DingTalkDocError, read_dingtalk_doc, resolve_dingtalk_operator


class DingTalkOperatorResolutionTest(unittest.TestCase):
    def test_read_sheet_uses_workbook_id_from_wiki_node_info(self) -> None:
        config = {
            "configName": "default",
            "appName": "JDB小钉",
            "appKey": "fake-key",
            "appSecret": "fake-secret",
            "operatorId": "union-1",
            "tokenHeaderName": "x-acs-dingtalk-access-token",
            "accessToken": "cached-token",
            "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(hours=1),
            "sheet_listUrlTemplate": "https://example.invalid/workbooks/{nodeId}/sheets?operatorId={operatorIdEncoded}",
            "sheet_rangeUrlTemplate": (
                "https://example.invalid/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}"
                "?operatorId={operatorIdEncoded}"
            ),
        }
        calls = []

        def fake_request(method, url, payload, headers, timeout):
            calls.append((method, url, payload, headers, timeout))
            if "api.dingtalk.com/v2.0/wiki/nodes/link-node" in url:
                return {"node": {"nodeId": "real-workbook", "extension": "axls", "name": "sheet-doc"}}
            if "example.invalid/workbooks/real-workbook/sheets?" in url:
                return {"value": [{"id": "sheet-1", "name": "Sheet1"}]}
            if "example.invalid/workbooks/real-workbook/sheets/sheet-1/ranges/A1%3AB2" in url:
                return {"values": [["A", "B"]]}
            raise AssertionError(f"unexpected url: {url}")

        with patch("app.dingtalk_docs.db.find_dingtalk_app_config", return_value=config), patch(
            "app.dingtalk_docs._request_json", side_effect=fake_request
        ):
            result = read_dingtalk_doc(node_id="link-node", cell_range="A1:B2", timeout=30)

        self.assertTrue(result["ok"])
        self.assertEqual(result["nodeId"], "link-node")
        self.assertEqual(result["workbookId"], "real-workbook")
        self.assertEqual(result["extension"], "axls")
        self.assertEqual(result["sheetId"], "sheet-1")
        self.assertIn("v2.0/wiki/nodes/link-node", calls[0][1])
        self.assertIn("workbooks/real-workbook/sheets", calls[1][1])

    def test_read_sheet_accepts_explicit_workbook_id_when_doc_info_fails(self) -> None:
        config = {
            "configName": "default",
            "appName": "JDB小钉",
            "appKey": "fake-key",
            "appSecret": "fake-secret",
            "operatorId": "union-1",
            "tokenHeaderName": "x-acs-dingtalk-access-token",
            "accessToken": "cached-token",
            "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(hours=1),
            "doc_infoUrlTemplate": "https://example.invalid/nodes/{nodeId}",
            "sheet_listUrlTemplate": "https://example.invalid/workbooks/{nodeId}/sheets",
            "sheet_rangeUrlTemplate": "https://example.invalid/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}",
        }

        def fake_request(method, url, payload, headers, timeout):
            if "example.invalid/nodes/link-node" in url:
                raise DingTalkDocError("DingTalk doc_info failed: missing permission")
            if "example.invalid/workbooks/explicit-workbook/sheets" in url and "/ranges/" not in url:
                return {"value": [{"id": "sheet-1", "name": "Sheet1"}]}
            if "example.invalid/workbooks/explicit-workbook/sheets/sheet-1/ranges/A1%3AB2" in url:
                return {"values": [["A", "B"]]}
            raise AssertionError(f"unexpected url: {url}")

        with patch("app.dingtalk_docs.db.find_dingtalk_app_config", return_value=config), patch(
            "app.dingtalk_docs._request_json", side_effect=fake_request
        ):
            result = read_dingtalk_doc(
                node_id="link-node",
                workbook_id="explicit-workbook",
                kind="axls",
                cell_range="A1:B2",
                timeout=30,
            )

        self.assertEqual(result["workbookId"], "explicit-workbook")
        self.assertEqual(result["sheetId"], "sheet-1")

    def test_resolve_operator_reads_union_id_from_user_detail(self) -> None:
        config = {
            "configName": "default",
            "appName": "JDB小钉",
            "appKey": "fake-key",
            "appSecret": "fake-secret",
            "tokenHeaderName": "x-acs-dingtalk-access-token",
            "accessToken": "cached-token",
            "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        calls = []

        def fake_request(method, url, payload, headers, timeout):
            calls.append((method, url, payload, headers, timeout))
            return {"unionId": "union-1"}

        with patch("app.dingtalk_docs.db.find_dingtalk_app_config", return_value=config), patch(
            "app.dingtalk_docs._request_json", side_effect=fake_request
        ):
            result = resolve_dingtalk_operator(user_id="055817303522912272", timeout=30)

        self.assertEqual(result["configName"], "default")
        self.assertEqual(result["appName"], "JDB小钉")
        self.assertEqual(result["userId"], "055817303522912272")
        self.assertEqual(result["unionId"], "union-1")
        self.assertEqual(calls[0][0], "GET")
        self.assertEqual(
            calls[0][1],
            "https://api.dingtalk.com/v1.0/contact/users/055817303522912272",
        )
        self.assertEqual(calls[0][3], {"x-acs-dingtalk-access-token": "cached-token"})

    def test_resolve_operator_falls_back_to_oapi_user_detail_on_not_found(self) -> None:
        config = {
            "configName": "default",
            "appName": "JDB小钉",
            "appKey": "fake-key",
            "appSecret": "fake-secret",
            "tokenHeaderName": "x-acs-dingtalk-access-token",
            "accessToken": "cached-token",
            "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        calls = []

        def fake_request(method, url, payload, headers, timeout):
            calls.append((method, url, payload, headers, timeout))
            if "api.dingtalk.com/v1.0/contact/users" in url:
                raise DingTalkDocError("DingTalk API failed: status=404 找不到该用户")
            if "oapi.dingtalk.com/gettoken" in url:
                return {"errcode": 0, "access_token": "oapi-token"}
            if "oapi.dingtalk.com/topapi/v2/user/get" in url:
                return {"errcode": 0, "result": {"unionid": "union-from-oapi"}}
            raise AssertionError(f"unexpected url: {url}")

        with patch("app.dingtalk_docs.db.find_dingtalk_app_config", return_value=config), patch(
            "app.dingtalk_docs._request_json", side_effect=fake_request
        ):
            result = resolve_dingtalk_operator(user_id="055817303522912272", timeout=30)

        self.assertEqual(result["unionId"], "union-from-oapi")
        self.assertEqual(result["source"], "oapi_v2")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][0], "POST")
        self.assertIn("access_token=oapi-token", calls[2][1])
        self.assertEqual(calls[2][2], {"userid": "055817303522912272", "language": "zh_CN"})


if __name__ == "__main__":
    unittest.main()
