import unittest
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


class YunxiaoDbConfigTest(unittest.TestCase):
    def test_find_yunxiao_project_config_reads_project_mapping(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = {
            "project_name": "jdb-school-crm",
            "account_name": "main-ak",
            "organization_id": "org-1",
            "project_id": "project-1",
            "sprint_id": "sprint-1",
            "workitem_category": "Req",
            "workitem_type_identifier": "type-req",
            "default_assignee": "user-1",
            "priority_field_id": "priority",
            "priority_default_value": "P2",
            "participants": "u2,u3",
            "trackers": "u4",
            "verifier": "u5",
            "done_status_id": "done",
            "done_status_field_id": "status",
            "done_status_names": "已完成,已关闭",
            "comment_field_key": "description",
            "comment_format_type": "MARKDOWN",
            "close_transition_id": "transition-done",
            "remark": "crm project",
        }

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_yunxiao_project_config("jdb-school-crm")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["projectName"], "jdb-school-crm")
        self.assertEqual(result["accountName"], "main-ak")
        self.assertEqual(result["organizationId"], "org-1")
        self.assertEqual(result["projectId"], "project-1")
        self.assertEqual(result["sprintId"], "sprint-1")
        self.assertEqual(result["workitemTypeIdentifier"], "type-req")
        self.assertEqual(result["assignee"], "user-1")
        self.assertEqual(result["doneStatusId"], "done")
        self.assertEqual(result["doneStatusFieldId"], "status")
        self.assertEqual(result["doneStatusNames"], "已完成,已关闭")
        self.assertEqual(result["commentFieldKey"], "description")
        self.assertEqual(result["commentFormatType"], "MARKDOWN")
        self.assertEqual(result["closeTransitionId"], "transition-done")
        sql = cursor.execute.call_args.args[0]
        self.assertIn("adapter_yunxiao_project_config", sql)
        self.assertIn("LOWER(project_name)", sql)

    def test_find_yunxiao_account_config_reads_account_ak_mapping(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = {
            "account_name": "main-ak",
            "auth_type": "acs_ak",
            "access_key_id": "ak-id",
            "access_key_secret": "ak-secret",
            "legacy_token": None,
            "security_token": "sts-token",
            "endpoint": "devops.cn-hangzhou.aliyuncs.com",
            "remark": "main account",
        }

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_yunxiao_account_config("main-ak")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["accountName"], "main-ak")
        self.assertEqual(result["authType"], "acs_ak")
        self.assertEqual(result["accessKeyId"], "ak-id")
        self.assertEqual(result["accessKeySecret"], "ak-secret")
        self.assertIsNone(result["legacyToken"])
        self.assertEqual(result["securityToken"], "sts-token")
        self.assertEqual(result["endpoint"], "devops.cn-hangzhou.aliyuncs.com")
        sql = cursor.execute.call_args.args[0]
        self.assertIn("adapter_yunxiao_account_config", sql)
        self.assertIn("LOWER(account_name)", sql)

    def test_find_yunxiao_project_member_reads_member_by_name_or_id(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = {
            "project_name": "jdb-school-crm",
            "member_name": "姬志猛",
            "yunxiao_account_id": "user-jzm",
            "is_default": 1,
            "enabled": 1,
            "remark": "owner",
        }

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_yunxiao_project_member("jdb-school-crm", "姬志猛")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["projectName"], "jdb-school-crm")
        self.assertEqual(result["name"], "姬志猛")
        self.assertEqual(result["accountId"], "user-jzm")
        self.assertTrue(result["isDefault"])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("adapter_yunxiao_project_member", sql)
        self.assertIn("LOWER(member_name)", sql)
        self.assertIn("yunxiao_account_id", sql)

    def test_find_default_yunxiao_project_member_reads_default_member(self) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = {
            "project_name": "jdb-school-crm",
            "member_name": "姬志猛",
            "yunxiao_account_id": "user-jzm",
            "is_default": 1,
            "enabled": 1,
            "remark": "owner",
        }

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_default_yunxiao_project_member("jdb-school-crm")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["name"], "姬志猛")
        self.assertEqual(result["accountId"], "user-jzm")
        sql = cursor.execute.call_args.args[0]
        self.assertIn("is_default = 1", sql)
        self.assertIn("ORDER BY updated_at DESC", sql)


if __name__ == "__main__":
    unittest.main()
