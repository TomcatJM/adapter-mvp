# AI研发闭环一期并行任务临时清单

> 临时协作文件，用于多个 Codex 会话并行实现一期能力。完成集成验收后，可归档到 `delivery/docs/` 或删除。

## 总目标

一期先跑通：

```text
多项目配置
-> 知识图谱查询
-> CodeGraph 索引回调入库
-> CI 生成并上传 OSS 索引
-> Worker 查询影响面
-> workflow 保存 knowledgeContext
-> Codex 基于上下文生成需求模板和 coding spec
```

一期不做：

- 自动合并 develop
- 自动关单
- 全量 AI 编码代理
- 把 CodeGraph 索引提交到 Git

## 会话 A：项目配置与 DB 基础

目标：

- 新增 `adapter_project_config`
- 新增 `adapter_codegraph_index`
- 提供项目配置查询和 CodeGraph 索引 upsert 能力

状态：已完成本地实现，等待最终集成验收。

主要文件：

- `app/db.py`
- `delivery/sql/mysql_schema.sql`
- 可新增 `scripts/upsert_adapter_project_config.py`
- 可新增 `tests/test_project_config.py`
- 可扩展 `tests/test_primary_key_relations.py`

建议字段：

`adapter_project_config`

```text
id
project_key
project_name
knowledge_endpoint
codegraph_enabled
codegraph_strategy
oss_bucket
oss_prefix
remark
created_at
updated_at
```

`adapter_codegraph_index`

```text
id
project_key
branch_name
commit_id
index_version
storage_type
bucket_name
object_key
status_object_key
sha256_object_key
index_status
stats_json
error_message
created_at
updated_at
```

验收：

- `ensure_schema()` 能创建/补齐两张表。
- 能按 `projectKey` 查询项目配置。
- 能 upsert CodeGraph 索引记录。
- 同一 `projectKey + branchName + commitId + indexVersion` 重复回调幂等。
- 缺少项目配置时明确失败，不走静默默认项目。

## 会话 B：知识图谱代理接口

目标：

- 新增 `/adapter/knowledge/query`
- Adapter 根据 `projectKey` 找项目知识图谱地址，并代理查询

状态：已完成本地实现，等待最终集成验收。

主要文件：

- `app/main.py`
- `app/models.py`
- 建议新增 `app/knowledge.py`
- 可新增 `tests/test_knowledge_query.py`

依赖：

- 会话 A 提供 `find_adapter_project_config(project_key)` 或同等函数。

接口：

```http
POST /adapter/knowledge/query
Authorization: Bearer <token>
```

入参：

```json
{
  "projectKey": "jdb-school-crm",
  "question": "创建一条线索大概逻辑是什么",
  "mode": "ai"
}
```

验收：

- 未配置 `projectKey` 明确失败。
- 未配置 `knowledgeEndpoint` 明确失败。
- 能代理调用项目知识图谱接口。
- 响应结构能归一成 `businessAnswer`、`developerEntrypoints`、`aiPlanHints`、`documents`。
- 不打印 token、cookie、Authorization。

## 会话 C：CodeGraph 索引回调接口

目标：

- 新增 `/adapter/codegraph/index-callback`
- 让流水线把 CodeGraph 索引结果写回 Adapter

主要文件：

- `app/main.py`
- `app/models.py`
- 建议新增 `app/codegraph.py`
- 可新增 `tests/test_codegraph_index_callback.py`

依赖：

- 会话 A 提供 `upsert_codegraph_index(...)` 或同等函数。

接口：

```http
POST /adapter/codegraph/index-callback
Authorization: Bearer <token>
```

入参：

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "indexVersion": "abc123-20260702",
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

验收：

- 成功回调入库。
- 失败回调也入库，并记录 `errorMessage`。
- 重复回调幂等。
- 缺少项目配置明确失败。
- 有 `workflowId` 时可推进 `CODEGRAPH_INDEXED`；没有 `workflowId` 时只记录索引版本，不猜 workflow。

## 会话 D：CI / OSS 索引上传脚本

目标：

- 提供流水线可直接执行的 CodeGraph 索引生成和上传脚本

状态：已完成本地实现，等待会话 C 接口稳定后做联调。

后续完善待办：

- 当前先用 `OSS_BUCKET` / `OSS_PREFIX` 环境变量跑通全流程。
- 全流程跑通后，再改为脚本按 `PROJECT_KEY` 调 Adapter 查询 `adapter_project_config` 中的 OSS 路径配置。
- OSS AK/SK/STS 不进代码、不进文档；仍放云效/Codeup 流水线密钥变量或 `ossutil` 本机 profile。
- 最终目标：OSS 路径配置进 DB，OSS 写权限凭证留在流水线密钥侧，Adapter 只记录索引元数据。

建议新增：

- `scripts/codegraph_build_and_upload.sh`
- `delivery/docs/CodeGraph流水线接入说明.md`

脚本流程：

```bash
codegraph telemetry off
codegraph index .
codegraph status . --json > codegraph-status.json
tar -czf codegraph-index.tar.gz .codegraph codegraph-status.json
sha256sum codegraph-index.tar.gz > sha256.txt
ossutil cp codegraph-index.tar.gz "oss://${OSS_BUCKET}/${OSS_PREFIX}/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/"
ossutil cp codegraph-status.json "oss://${OSS_BUCKET}/${OSS_PREFIX}/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/"
ossutil cp sha256.txt "oss://${OSS_BUCKET}/${OSS_PREFIX}/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/"
curl -X POST "${ADAPTER_BASE_URL}/adapter/codegraph/index-callback" ...
```

必需环境变量：

```text
PROJECT_KEY
BRANCH_NAME
COMMIT_ID
OSS_BUCKET
OSS_PREFIX
ADAPTER_BASE_URL
ADAPTER_API_TOKEN
```

验收：

- 缺参数直接失败。
- 不打印 token。
- 支持 dry-run 更好。
- 回调请求体与会话 C 接口一致。

已交付：

- `scripts/codegraph_build_and_upload.sh`
- `delivery/docs/CodeGraph流水线接入说明.md`
- `tests/test_codegraph_build_script.py`

## 会话 E：CodeGraph Worker

目标：

- 在 47 上部署轻量 CodeGraph 查询服务
- Adapter 后续通过本机地址调用它

状态：已完成 47 部署和真实 OSS 联调。

建议新增目录：

- `codegraph_worker/`
- `codegraph_worker/main.py`
- `codegraph_worker/README.md`

接口：

```http
POST /codegraph/query
```

职责：

```text
1. 根据 projectKey / branchName / commitId / indexVersion 定位索引。
2. 从 OSS 下载 codegraph-index.tar.gz。
3. 校验 sha256。
4. 解压到本地缓存。
5. 执行 impact / callers / callees / node 查询。
6. 返回结构化结果。
```

部署约束：

```text
监听地址：127.0.0.1:18081
缓存目录：/opt/codegraph-cache
服务目录：/opt/codegraph-worker
并发限制：一期先 1
Worker 只持有 OSS 只读凭证
不对公网开放
```

验收：

- 缺索引明确报错。
- sha256 不匹配明确报错。
- 查询失败明确报错。
- 成功时返回结构化影响面。

已交付：

- `codegraph_worker/service.py`
- `codegraph_worker/main.py`
- `codegraph_worker/README.md`
- `tests/test_codegraph_worker.py`
- `scripts/remote_install_codegraph_worker.sh`

部署验收：

- `codegraph-worker.service` 已在 47 上 `active/enabled`。
- 监听地址为 `127.0.0.1:18081`，公网 `18081` 不开放。
- Worker 已用真实 OSS 索引完成 `impact handle_index_callback` 查询。

## 会话 F：workflow 写入 knowledgeContext

目标：

- 把知识图谱结果和 CodeGraph 影响面保存进 workflow context

状态：已完成本地实现。

主要文件：

- `app/workflow.py`
- `app/db.py`
- `app/models.py`
- 可新增 `tests/test_workflow_knowledge_context.py`

已交付：

- `app/workflow.py`
- `tests/test_workflow_p0.py`

实现说明：

- `WorkflowRequirementRequest.extra.knowledgeContext` 会写入顶层 `context.knowledgeContext`。
- `WorkflowCodingResultRequest.extra.knowledgeContext` 会写入或覆盖顶层 `context.knowledgeContext`。
- 原始 `extra.knowledgeContext` 仍保留在 `context.requirement.extra` 或 `context.codingResult.extra` 中。

建议结构：

```json
{
  "knowledgeContext": {
    "projectKey": "jdb-school-crm",
    "businessKnowledge": {},
    "codeImpact": {},
    "branchName": "develop",
    "commitId": "abc123",
    "indexVersion": "abc123-20260702"
  }
}
```

验收：

- 可写入 workflow context。
- 可重复更新。
- 不覆盖已有 requirement / coding result / pipeline 信息。
- 可推进到 `KNOWLEDGE_CONTEXT_READY`。

## 会话 G：模板与文档

目标：

- 固化需求模板和 coding spec 格式
- 更新一期进度文档

建议新增：

- `delivery/templates/需求上下文模板.md`
- `delivery/templates/coding-spec模板.md`

主要更新：

- `delivery/docs/AI研发闭环与多项目CodeGraph接入进度.md`
- `delivery/docs/接口文档.md`
- `delivery/docs/文档索引.md`

验收：

- 模板明确引用 `knowledgeContext`。
- 文档标清已实现和仍需配置项。
- 不写入真实 token、AK、SK、OSS 凭证。

## 推荐并行顺序

第一批：

```text
A：项目配置与 DB 基础
G：模板与文档草案
```

第二批，等 A 的函数名和字段定下来：

```text
B：知识图谱代理接口
C：CodeGraph 索引回调接口
D：CI / OSS 索引上传脚本
```

第三批：

```text
E：CodeGraph Worker
F：workflow 写入 knowledgeContext
```

## 统一验收命令

每个会话完成后至少跑相关测试。最终合并验收跑：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall app scripts
git diff --check
```

## 集成验收口径

最终至少证明：

1. 能注册一个 `projectKey`。
2. 调 `/adapter/knowledge/query` 能拿到业务知识。
3. 模拟 `/adapter/codegraph/index-callback` 能写入索引版本。
4. workflow 能保存 `knowledgeContext`。
5. Worker 接入后，能用 OSS 索引查影响面。
