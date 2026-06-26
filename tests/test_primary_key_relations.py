from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrimaryKeyRelationsTest(unittest.TestCase):
    def test_schema_adds_surrogate_id_relation_columns_for_config_tables(self) -> None:
        schema_sql = (ROOT / "delivery" / "sql" / "mysql_schema.sql").read_text(encoding="utf-8")

        self.assertIn("account_config_id BIGINT NULL", schema_sql)
        self.assertIn("project_config_id BIGINT NULL", schema_sql)
        self.assertIn("member_id BIGINT NULL", schema_sql)
        self.assertIn("apifox_project_config_id BIGINT NULL", schema_sql)

    def test_upsert_scripts_write_surrogate_relation_ids(self) -> None:
        yunxiao_script = (ROOT / "scripts" / "upsert_yunxiao_config.py").read_text(encoding="utf-8")
        apifox_script = (ROOT / "scripts" / "upsert_apifox_pipeline_config.py").read_text(encoding="utf-8")

        self.assertIn("account_config_id", yunxiao_script)
        self.assertIn("project_config_id", yunxiao_script)
        self.assertIn("member_id", yunxiao_script)
        self.assertIn("apifox_project_config_id", apifox_script)


if __name__ == "__main__":
    unittest.main()
