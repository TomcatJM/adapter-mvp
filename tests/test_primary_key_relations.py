from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrimaryKeyRelationsTest(unittest.TestCase):
    def test_schema_adds_surrogate_id_relation_columns_for_config_tables(self) -> None:
        schema_sql = (ROOT / "delivery" / "sql" / "mysql_schema.sql").read_text(encoding="utf-8")
        pipeline_table_sql = schema_sql.split("CREATE TABLE IF NOT EXISTS adapter_apifox_pipeline_config", 1)[1].split(
            "CREATE TABLE IF NOT EXISTS adapter_project_config",
            1,
        )[0]

        self.assertIn("adapter_apifox_account_config", schema_sql)
        self.assertIn("Apifox Access Token", schema_sql)
        self.assertIn("account_config_id BIGINT NULL", schema_sql)
        self.assertIn("import_delay_seconds INT NOT NULL DEFAULT 0", schema_sql)
        self.assertIn("project_config_id BIGINT NULL", schema_sql)
        self.assertIn("member_id BIGINT NULL", schema_sql)
        self.assertIn("pipeline_name VARCHAR(256) NULL", pipeline_table_sql)
        self.assertIn("service_name VARCHAR(128) NOT NULL", pipeline_table_sql)
        self.assertIn("env_name VARCHAR(64) NOT NULL", pipeline_table_sql)
        self.assertIn("repo_name VARCHAR(128) NULL", pipeline_table_sql)
        self.assertIn("apifox_project_config_id BIGINT NOT NULL", pipeline_table_sql)
        self.assertNotIn("project_name", pipeline_table_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS adapter_project_config", schema_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS adapter_codegraph_index", schema_sql)

    def test_upsert_scripts_write_surrogate_relation_ids(self) -> None:
        yunxiao_script = (ROOT / "scripts" / "upsert_yunxiao_config.py").read_text(encoding="utf-8")
        apifox_script = (ROOT / "scripts" / "upsert_apifox_pipeline_config.py").read_text(encoding="utf-8")
        apifox_account_script = (ROOT / "scripts" / "upsert_apifox_account_config.py").read_text(encoding="utf-8")
        apifox_project_script = (ROOT / "scripts" / "upsert_apifox_project_config.py").read_text(encoding="utf-8")
        adapter_project_script = (ROOT / "scripts" / "upsert_adapter_project_config.py").read_text(encoding="utf-8")

        self.assertIn("account_config_id", yunxiao_script)
        self.assertIn("project_config_id", yunxiao_script)
        self.assertIn("member_id", yunxiao_script)
        self.assertIn("adapter_apifox_account_config", apifox_account_script)
        self.assertIn("account_config_id", apifox_project_script)
        self.assertIn("--import-delay-seconds", apifox_project_script)
        self.assertIn("apifox_project_config_id", apifox_script)
        self.assertIn("--apifox-project-config-id", apifox_script)
        self.assertIn("--service-name", apifox_script)
        self.assertIn("--env-name", apifox_script)
        self.assertIn("--repo-name", apifox_script)
        self.assertNotIn("--project-name", apifox_script)
        self.assertIn("--project-key", adapter_project_script)
        self.assertIn("--knowledge-endpoint", adapter_project_script)


if __name__ == "__main__":
    unittest.main()
