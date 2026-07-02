import hashlib
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codegraph_worker.service import CodeGraphQuery, CodeGraphWorker, WorkerConfig, WorkerError


class CodeGraphWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.cache_root = self.tmpdir / "cache"
        self.remote = self.tmpdir / "remote"
        self.remote.mkdir()
        self.index_tar = self.remote / "codegraph-index.tar.gz"
        self.status = self.remote / "codegraph-status.json"
        self.sha = self.remote / "sha256.txt"
        self._create_index_tar(self.index_tar)
        self.status.write_text(json.dumps({"files": 1, "nodes": 2, "edges": 3}), encoding="utf-8")
        digest = hashlib.sha256(self.index_tar.read_bytes()).hexdigest()
        self.sha.write_text(f"{digest}  codegraph-index.tar.gz\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir)

    def test_successful_query_downloads_validates_extracts_and_runs_codegraph(self) -> None:
        worker = CodeGraphWorker(
            WorkerConfig(
                cache_root=self.cache_root,
                ossutil_bin="ossutil-test",
                codegraph_bin="codegraph-test",
            )
        )
        request = self._query()

        with patch("codegraph_worker.service.subprocess.run", side_effect=self._fake_subprocess) as run:
            result = worker.query(request)

        self.assertTrue(result["ok"])
        self.assertEqual(result["queryType"], "impact")
        self.assertEqual(result["result"], {"symbols": ["ClientService.create"]})
        self.assertEqual(result["status"], {"files": 1, "nodes": 2, "edges": 3})
        self.assertEqual(run.call_count, 4)
        self.assertTrue((self.cache_root / "jdb-school-crm" / "develop" / "abc123" / "abc123-20260702" / ".ready").exists())

    def test_sha256_mismatch_fails_explicitly(self) -> None:
        self.sha.write_text(f"{'0' * 64}  codegraph-index.tar.gz\n", encoding="utf-8")
        worker = CodeGraphWorker(WorkerConfig(cache_root=self.cache_root))

        with patch("codegraph_worker.service.subprocess.run", side_effect=self._fake_subprocess):
            with self.assertRaises(WorkerError) as raised:
                worker.query(self._query())

        self.assertIn("sha256 mismatch", str(raised.exception))

    def test_codegraph_command_failure_is_reported(self) -> None:
        worker = CodeGraphWorker(WorkerConfig(cache_root=self.cache_root))

        def fake_run(args, **kwargs):
            completed = self._fake_subprocess(args, **kwargs)
            if args[0] == "codegraph":
                completed.returncode = 2
                completed.stderr = "query failed"
            return completed

        with patch("codegraph_worker.service.subprocess.run", side_effect=fake_run):
            with self.assertRaises(WorkerError) as raised:
                worker.query(self._query())

        self.assertIn("codegraph query failed", str(raised.exception))

    def _query(self) -> CodeGraphQuery:
        return CodeGraphQuery(
            projectKey="jdb-school-crm",
            branchName="develop",
            commitId="abc123",
            indexVersion="abc123-20260702",
            bucketName="ai-dev-artifacts",
            objectKey="codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
            statusObjectKey="codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
            sha256ObjectKey="codegraph/jdb-school-crm/develop/abc123/sha256.txt",
            queryType="impact",
            target="ClientService.create",
        )

    def _fake_subprocess(self, args, **kwargs):
        class Completed:
            def __init__(self, returncode=0, stdout="", stderr="") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if args[0] == "ossutil-test" or args[0] == "ossutil":
            object_key = args[2].replace("oss://ai-dev-artifacts/", "")
            destination = Path(args[3])
            source = {
                "codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz": self.index_tar,
                "codegraph/jdb-school-crm/develop/abc123/codegraph-status.json": self.status,
                "codegraph/jdb-school-crm/develop/abc123/sha256.txt": self.sha,
            }[object_key]
            shutil.copyfile(source, destination)
            return Completed()
        if args[0] == "codegraph-test" or args[0] == "codegraph":
            self.assertEqual(args[1:3], ["impact", "ClientService.create"])
            return Completed(stdout=json.dumps({"symbols": ["ClientService.create"]}))
        raise AssertionError(f"unexpected command: {args}")

    def _create_index_tar(self, path: Path) -> None:
        source = self.tmpdir / "source"
        (source / ".codegraph").mkdir(parents=True)
        (source / ".codegraph" / "index.json").write_text("{}", encoding="utf-8")
        with tarfile.open(path, "w:gz") as archive:
            archive.add(source / ".codegraph", arcname=".codegraph")


if __name__ == "__main__":
    unittest.main()
