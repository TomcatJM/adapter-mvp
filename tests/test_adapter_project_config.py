import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db


ROOT = Path(__file__).resolve().parents[1]


class _FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AdapterProjectConfigTest(unittest.TestCase):
    def test_schema_contains_project_and_codegraph_index_tables(self) -> None:
        schema_sql = (ROOT / "delivery" / "sql" / "mysql_schema.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS adapter_project_config", schema_sql)
        self.assertIn("project_key VARCHAR(128) NOT NULL", schema_sql)
        self.assertIn("knowledge_endpoint VARCHAR(2048) NULL", schema_sql)
        self.assertIn("codegraph_enabled TINYINT(1) NOT NULL DEFAULT 0", schema_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS adapter_codegraph_index", schema_sql)
        self.assertIn("UNIQUE KEY uk_adapter_codegraph_index_version", schema_sql)

    def test_find_adapter_project_config_maps_row_to_camel_case(self) -> None:
        cursor = _FakeCursor(
            {
                "id": 7,
                "project_key": "jdb-school-crm",
                "project_name": "校CRM",
                "knowledge_endpoint": "http://example.test/white/KnowledgeGraph/query",
                "codegraph_enabled": 1,
                "codegraph_strategy": "oss-artifact",
                "oss_bucket": "ai-dev-artifacts",
                "oss_prefix": "codegraph/jdb-school-crm",
                "remark": "demo",
            }
        )

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            result = db.find_adapter_project_config("JDB-SCHOOL-CRM")

        self.assertEqual(
            result,
            {
                "projectConfigId": 7,
                "projectKey": "jdb-school-crm",
                "projectName": "校CRM",
                "knowledgeEndpoint": "http://example.test/white/KnowledgeGraph/query",
                "codegraphEnabled": True,
                "codegraphStrategy": "oss-artifact",
                "ossBucket": "ai-dev-artifacts",
                "ossPrefix": "codegraph/jdb-school-crm",
                "remark": "demo",
            },
        )
        self.assertIn("LOWER(project_key) = LOWER(%s)", cursor.statements[0][0])
        self.assertEqual(cursor.statements[0][1], ("JDB-SCHOOL-CRM",))

    def test_upsert_codegraph_index_writes_idempotent_row(self) -> None:
        cursor = _FakeCursor()

        with patch("app.db.configured", return_value=True), patch("app.db.ensure_schema"), patch(
            "app.db.connect", return_value=_FakeConnection(cursor)
        ):
            db.upsert_codegraph_index(
                project_key="jdb-school-crm",
                branch_name="develop",
                commit_id="abc123",
                index_version="abc123-20260702",
                storage_type="oss",
                bucket_name="ai-dev-artifacts",
                object_key="codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
                status_object_key="codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
                sha256_object_key="codegraph/jdb-school-crm/develop/abc123/sha256.txt",
                index_status="success",
                stats={"files": 1, "nodes": 2, "edges": 3},
                error_message=None,
            )

        statement, params = cursor.statements[0]
        self.assertIn("INSERT INTO adapter_codegraph_index", statement)
        self.assertIn("ON DUPLICATE KEY UPDATE", statement)
        self.assertIn("stats_json = VALUES(stats_json)", statement)
        self.assertEqual(params[0:4], ("jdb-school-crm", "develop", "abc123", "abc123-20260702"))
        self.assertEqual(json.loads(params[10]), {"files": 1, "nodes": 2, "edges": 3})

    def test_upsert_project_script_exists_and_never_accepts_secret_values(self) -> None:
        script = (ROOT / "scripts" / "upsert_adapter_project_config.py").read_text(encoding="utf-8")

        self.assertIn("--project-key", script)
        self.assertIn("--knowledge-endpoint", script)
        self.assertIn("--oss-bucket", script)
        self.assertIn("--oss-prefix", script)
        self.assertNotIn("token", script.lower())
        self.assertNotIn("secret", script.lower())


if __name__ == "__main__":
    unittest.main()
