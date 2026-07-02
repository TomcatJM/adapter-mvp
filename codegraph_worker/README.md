# CodeGraph Worker

Lightweight local worker for querying CodeGraph indexes produced by CI and stored in OSS.

## Runtime

Recommended deployment:

```text
host: 47 server
listen: 127.0.0.1:18081
service dir: /opt/codegraph-worker
cache dir: /opt/codegraph-cache
```

The worker should not be exposed publicly. Adapter calls it locally.

## Environment

```text
CODEGRAPH_WORKER_CACHE_ROOT=/opt/codegraph-cache
CODEGRAPH_WORKER_OSSUTIL_BIN=ossutil
CODEGRAPH_WORKER_CODEGRAPH_BIN=codegraph
```

OSS credentials stay in the host or service environment used by `ossutil`. The worker only needs read access to CodeGraph artifacts.

## API

```http
POST /codegraph/query
```

Example:

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "indexVersion": "abc123-20260702",
  "bucketName": "ai-dev-artifacts",
  "objectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
  "statusObjectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
  "sha256ObjectKey": "codegraph/jdb-school-crm/develop/abc123/sha256.txt",
  "queryType": "impact",
  "target": "ClientService.create"
}
```

Supported `queryType` values:

```text
impact
callers
callees
node
explore
```

## Start

```bash
uvicorn codegraph_worker.main:app --host 127.0.0.1 --port 18081
```

Remote systemd install:

```bash
APP_DIR=/opt/codegraph-worker \
CACHE_DIR=/opt/codegraph-cache \
PORT=18081 \
bash scripts/remote_install_codegraph_worker.sh
```

The installer requires `codegraph` and `ossutil` to be installed on the host
before starting the service. It creates `/etc/adapter-mvp/codegraph-worker.env`
on first install if the file does not already exist.

## Safety

- Verifies `sha256.txt` before extracting an index archive.
- Rejects unsafe archive paths.
- Caches prepared indexes under `CODEGRAPH_WORKER_CACHE_ROOT`.
- Does not print or store OSS credentials.
