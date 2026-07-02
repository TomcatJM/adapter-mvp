# CodeGraph 流水线接入说明

本文说明会话 D 的交付内容：在 Codeup / 云效流水线中生成 CodeGraph 索引、上传 OSS，并回调 Adapter 记录索引版本。

## 1. 脚本

脚本路径：

```bash
scripts/codegraph_build_and_upload.sh
```

脚本会执行：

```text
codegraph telemetry off
codegraph index .
codegraph status . --json > codegraph-status.json
tar -czf codegraph-index.tar.gz .codegraph codegraph-status.json
生成 sha256.txt
上传三份产物到 OSS
POST /adapter/codegraph/index-callback
```

## 2. 必需环境变量

```text
PROJECT_KEY
BRANCH_NAME
COMMIT_ID
OSS_BUCKET
OSS_PREFIX
ADAPTER_BASE_URL
ADAPTER_API_TOKEN
```

可选环境变量：

```text
DRY_RUN=true
INDEX_VERSION
WORK_DIR
OUTPUT_DIR
CODEGRAPH_BIN
OSSUTIL_BIN
CURL_BIN
PYTHON_BIN
```

## 3. OSS 路径

上传目录格式：

```text
oss://${OSS_BUCKET}/${OSS_PREFIX}/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/
```

产物：

```text
codegraph-index.tar.gz
codegraph-status.json
sha256.txt
```

## 4. Adapter 回调

脚本上传完成后调用：

```http
POST /adapter/codegraph/index-callback
Authorization: Bearer <token>
```

请求体字段和会话 C 的接口保持一致：

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "indexVersion": "abc123",
  "storageType": "oss",
  "bucketName": "ai-dev-artifacts",
  "objectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
  "statusObjectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
  "sha256ObjectKey": "codegraph/jdb-school-crm/develop/abc123/sha256.txt",
  "indexStatus": "success",
  "stats": {
    "files": 1642,
    "nodes": 51655,
    "edges": 84017
  }
}
```

## 5. Dry Run

上线前先 dry-run 一次：

```bash
DRY_RUN=true \
PROJECT_KEY=jdb-school-crm \
BRANCH_NAME=develop \
COMMIT_ID=abc123 \
OSS_BUCKET=ai-dev-artifacts \
OSS_PREFIX=codegraph \
ADAPTER_BASE_URL=http://47.116.102.238:18080 \
ADAPTER_API_TOKEN=replace-with-token \
bash scripts/codegraph_build_and_upload.sh
```

dry-run 只打印目标路径和回调地址，不执行 `codegraph`、`ossutil` 或 Adapter 回调。

## 6. 安全要求

- 不要打印 `ADAPTER_API_TOKEN`。
- 不要把 OSS AK/SK、Adapter token、cookie 或 Authorization 写进文档、日志或提交记录。
- OSS bucket 应为私有 bucket。
- Worker 后续只持有 OSS 只读凭证。

