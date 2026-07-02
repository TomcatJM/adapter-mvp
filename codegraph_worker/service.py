from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkerError(RuntimeError):
    """Raised when the worker cannot prepare or query a CodeGraph index."""


class CodeGraphQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_key: str = Field(alias="projectKey")
    branch_name: str = Field(alias="branchName")
    commit_id: str = Field(alias="commitId")
    index_version: str = Field(alias="indexVersion")
    bucket_name: str = Field(alias="bucketName")
    object_key: str = Field(alias="objectKey")
    status_object_key: str | None = Field(default=None, alias="statusObjectKey")
    sha256_object_key: str = Field(alias="sha256ObjectKey")
    query_type: str = Field(alias="queryType")
    target: str


@dataclass(frozen=True)
class WorkerConfig:
    cache_root: Path
    ossutil_bin: str = "ossutil"
    codegraph_bin: str = "codegraph"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        return cls(
            cache_root=Path(os.getenv("CODEGRAPH_WORKER_CACHE_ROOT", "/opt/codegraph-cache")),
            ossutil_bin=os.getenv("CODEGRAPH_WORKER_OSSUTIL_BIN", "ossutil"),
            codegraph_bin=os.getenv("CODEGRAPH_WORKER_CODEGRAPH_BIN", "codegraph"),
        )


class CodeGraphWorker:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config

    def query(self, request: CodeGraphQuery) -> dict[str, Any]:
        query_type = _normalize_query_type(request.query_type)
        cache_dir = self._cache_dir(request)
        self._ensure_index_ready(request, cache_dir)
        result = self._run_codegraph(cache_dir, query_type, request.target)
        status = self._read_status(cache_dir)
        return {
            "ok": True,
            "projectKey": request.project_key,
            "branchName": request.branch_name,
            "commitId": request.commit_id,
            "indexVersion": request.index_version,
            "queryType": query_type,
            "target": request.target,
            "cachePath": str(cache_dir),
            "status": status,
            "result": result,
        }

    def _cache_dir(self, request: CodeGraphQuery) -> Path:
        return (
            self.config.cache_root
            / _safe_segment(request.project_key)
            / _safe_segment(request.branch_name)
            / _safe_segment(request.commit_id)
            / _safe_segment(request.index_version)
        )

    def _ensure_index_ready(self, request: CodeGraphQuery, cache_dir: Path) -> None:
        ready_marker = cache_dir / ".ready"
        if ready_marker.exists():
            return

        cache_dir.mkdir(parents=True, exist_ok=True)
        archive_path = cache_dir / "codegraph-index.tar.gz"
        sha_path = cache_dir / "sha256.txt"
        status_path = cache_dir / "codegraph-status.json"

        self._download(request.bucket_name, request.object_key, archive_path)
        self._download(request.bucket_name, request.sha256_object_key, sha_path)
        if request.status_object_key:
            self._download(request.bucket_name, request.status_object_key, status_path)

        expected = _read_expected_sha256(sha_path)
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if expected != actual:
            raise WorkerError(f"sha256 mismatch for {request.object_key}: expected {expected}, got {actual}")

        self._extract_archive(archive_path, cache_dir)
        ready_marker.write_text("ready\n", encoding="utf-8")

    def _download(self, bucket_name: str, object_key: str, destination: Path) -> None:
        source = f"oss://{bucket_name}/{object_key}"
        result = subprocess.run(
            [self.config.ossutil_bin, "cp", source, str(destination)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorkerError(f"oss download failed for {object_key}: {result.stderr or result.stdout}")

    def _extract_archive(self, archive_path: Path, destination: Path) -> None:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if not _is_relative_to(target, destination.resolve()):
                    raise WorkerError(f"unsafe archive path: {member.name}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise WorkerError(f"unsupported archive member: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise WorkerError(f"unable to extract archive member: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

    def _run_codegraph(self, cache_dir: Path, query_type: str, target: str) -> Any:
        result = subprocess.run(
            [self.config.codegraph_bin, query_type, target],
            cwd=str(cache_dir),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorkerError(f"codegraph query failed: {result.stderr or result.stdout}")
        output = result.stdout.strip()
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"raw": output}

    def _read_status(self, cache_dir: Path) -> dict[str, Any]:
        status_path = cache_dir / "codegraph-status.json"
        if not status_path.exists():
            return {}
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerError(f"invalid codegraph-status.json: {exc}") from exc


def _normalize_query_type(query_type: str) -> str:
    normalized = str(query_type or "").strip().lower()
    if normalized not in {"impact", "callers", "callees", "node", "explore"}:
        raise WorkerError("queryType must be one of impact, callers, callees, node, explore")
    return normalized


def _read_expected_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise WorkerError("sha256 file is empty")
    digest = content.split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise WorkerError(f"invalid sha256 digest: {digest}")
    return digest


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    if not segment or segment in {".", ".."}:
        raise WorkerError("invalid cache path segment")
    return segment


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
