import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app import db


class _FakeConnection:
    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def cursor(self):
        return self._cursor

    def close(self) -> None:
        pass


class DingTalkSplitConfigMappingTest(unittest.TestCase):
    def test_find_dingtalk_config_reads_joined_app_and_doc_tables(self) -> None:
        row = {
            "config_name": "default",
            "app_name": "JDB小钉",
            "app_key": "fake-key",
            "app_secret": "fake-secret",
            "auth_endpoint": "https://example.invalid/token",
            "token_header_name": "x-acs-dingtalk-access-token",
            "operator_id": "operator-1",
            "doc_info_method": "GET",
            "doc_info_url_template": "https://example.invalid/doc/{nodeId}",
            "doc_info_body_template": None,
            "doc_read_method": "GET",
            "doc_read_url_template": "https://example.invalid/doc/{nodeId}/content",
            "doc_read_body_template": None,
            "sheet_list_method": "GET",
            "sheet_list_url_template": "https://example.invalid/sheets/{nodeId}",
            "sheet_list_body_template": None,
            "sheet_range_method": "POST",
            "sheet_range_url_template": "https://example.invalid/range",
            "sheet_range_body_template": '{"range":"{range}"}',
            "access_token": "cached-token",
            "token_expires_at": datetime.now(timezone.utc),
            "remark": "doc read",
        }
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = row

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_dingtalk_app_config("default")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["configName"], "default")
        self.assertEqual(result["appName"], "JDB小钉")
        self.assertEqual(result["appKey"], "fake-key")
        self.assertEqual(result["sheet_rangeBodyTemplate"], {"range": "{range}"})
        first_sql = cursor.execute.call_args_list[0].args[0]
        self.assertIn("adapter_dingtalk_doc_config", first_sql)
        self.assertIn("adapter_dingtalk_app", first_sql)

    def test_update_dingtalk_token_cache_updates_app_table_by_doc_config(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.rowcount = 1
        expires_at = datetime.now(timezone.utc)

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            db.update_dingtalk_token_cache("default", "new-token", expires_at)

        self.assertEqual(cursor.execute.call_count, 1)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("UPDATE adapter_dingtalk_app app", sql)
        self.assertIn("JOIN adapter_dingtalk_doc_config cfg", sql)


if __name__ == "__main__":
    unittest.main()
