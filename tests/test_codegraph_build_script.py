from pathlib import Path
import os
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codegraph_build_and_upload.sh"
DOC = ROOT / "delivery" / "docs" / "CodeGraph流水线接入说明.md"


class CodeGraphBuildScriptTest(unittest.TestCase):
    def test_script_supports_required_env_dry_run_and_redacts_token(self) -> None:
        content = SCRIPT.read_text(encoding="utf-8")

        for name in (
            "PROJECT_KEY",
            "BRANCH_NAME",
            "COMMIT_ID",
            "OSS_BUCKET",
            "OSS_PREFIX",
            "ADAPTER_BASE_URL",
            "ADAPTER_API_TOKEN",
        ):
            self.assertIn(name, content)

        self.assertIn("DRY_RUN", content)
        self.assertIn("/adapter/codegraph/index-callback", content)
        self.assertIn("codegraph-index.tar.gz", content)
        self.assertIn("codegraph-status.json", content)
        self.assertIn("sha256.txt", content)
        self.assertIn('"${CODEGRAPH_BIN}" init .', content)
        self.assertIn("Authorization: Bearer", content)
        self.assertIn('WORK_DIR="$(cd "${WORK_DIR_INPUT}" && pwd)"', content)
        self.assertIn('OUTPUT_DIR="$(cd "${OUTPUT_DIR_INPUT}" && pwd)"', content)
        self.assertIn('-C "${OUTPUT_DIR}" codegraph-status.json', content)

        env = {
            **os.environ,
            "DRY_RUN": "true",
            "PROJECT_KEY": "jdb-school-crm",
            "BRANCH_NAME": "develop",
            "COMMIT_ID": "abc123",
            "OSS_BUCKET": "ai-dev-artifacts",
            "OSS_PREFIX": "codegraph",
            "ADAPTER_BASE_URL": "http://adapter.example.test",
            "ADAPTER_API_TOKEN": "secret-token-for-test",
        }
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("DRY_RUN=true", result.stdout)
        self.assertIn("oss://ai-dev-artifacts/codegraph/jdb-school-crm/develop/abc123/", result.stdout)
        self.assertNotIn("secret-token-for-test", result.stdout)
        self.assertNotIn("secret-token-for-test", result.stderr)

    def test_script_fails_fast_when_required_env_is_missing(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env={"PATH": os.environ.get("PATH", "")},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PROJECT_KEY is required", result.stderr)

    def test_script_is_documented(self) -> None:
        content = DOC.read_text(encoding="utf-8")

        self.assertIn("scripts/codegraph_build_and_upload.sh", content)
        self.assertIn("PROJECT_KEY", content)
        self.assertIn("DRY_RUN=true", content)
        self.assertIn("/adapter/codegraph/index-callback", content)
        self.assertIn("不要打印", content)


if __name__ == "__main__":
    unittest.main()
