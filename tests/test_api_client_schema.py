from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApiClientSchemaTest(unittest.TestCase):
    def test_api_client_schema_uses_hash_and_plaintext_token_fields(self) -> None:
        schema_sql = (ROOT / "delivery" / "sql" / "mysql_schema.sql").read_text(encoding="utf-8")
        upsert_script = (ROOT / "scripts" / "upsert_api_client.py").read_text(encoding="utf-8")

        self.assertIn("token_hash", schema_sql)
        self.assertIn("token_plaintext", schema_sql)
        self.assertIn("token_hash", upsert_script)
        self.assertIn("token_plaintext", upsert_script)
        self.assertNotIn("token_ciphertext", schema_sql)
        self.assertNotIn("token_last4", schema_sql)
        self.assertNotIn("token_ciphertext", upsert_script)
        self.assertNotIn("token_last4", upsert_script)


if __name__ == "__main__":
    unittest.main()
