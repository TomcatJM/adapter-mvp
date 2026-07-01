# AI研发闭环与多项目CodeGraph接入方案

## 一、总：整体目标

本方案目标是把 `adapter-mvp` 建成 AI 研发交付的中转层，串起产品需求、知识图谱、CodeGraph、OSS、云效、Codex、CI/CD、Apifox 和关单流程。

最终形态不是让 Adapter 自己做推理和编码，而是让它负责流程、状态、配置、鉴权、审计和外部系统调用；业务理解、代码影响面分析和编码分别交给知识图谱、CodeGraph Worker 和 Codex/Agent。

整体闭环：

```text
产品需求
  -> Adapter 创建 workflow
  -> 读取钉钉需求文档
  -> 查询项目知识图谱
  -> 查询当前项目最新 CodeGraph 索引版本
  -> CodeGraph Worker 从 OSS 下载索引并分析影响面
  -> Codex 生成澄清问题
  -> 产品确认后生成需求模板
  -> Adapter 创建云效任务
  -> Codex 生成 spec 并编码
  -> 代码提交并带任务号 / workflowId / 版本号
  -> 合并 develop
  -> 触发 CI/CD
  -> CI 生成新的 CodeGraph 索引并上传 OSS
  -> CI 成功后 Apifox 上传接口
  -> Adapter 关单
```

核心原则：

```text
Adapter 管流程，不做大脑。
Agent 管理解，不绕过状态机。
CodeGraph 管代码影响面，不替代业务知识图谱。
CodeGraph 索引不进 Git，由 CI 生成并存 OSS。
```

## 二、分：具体方案

## 1. 服务拆分与职责

| 服务 / 组件 | 主要职责 | 不负责 |
| --- | --- | --- |
| Adapter API | workflow 状态机、多项目配置、鉴权、审计、钉钉/云效/Apifox API、回调推进 | 大模型推理、重型索引、直接编码 |
| CodeGraph Worker | 下载 OSS 索引、校验、解压、缓存、执行 CodeGraph 查询 | workflow 状态、外部系统回调、业务决策 |
| Knowledge Graph | 业务视图、研发视图、AI 视图、问题索引、业务逻辑解释 | 代码索引、CI/CD |
| Codex / Agent | 需求澄清、需求模板、spec、coding、review、git 操作 | 持久化流程账本 |
| Codeup / 云效 | 仓库、任务、CI/CD、流水线回调 | 需求理解 |
| OSS | 保存 CodeGraph 索引产物 | 运行查询 |
| Apifox | 接口资产同步 | 需求和代码分析 |

推荐部署关系：

```text
47 服务器
  - Adapter API: 0.0.0.0:18080
  - CodeGraph Worker: 127.0.0.1:18081
  - CodeGraph 缓存: /opt/codegraph-cache

Codeup / 云效流水线
  - 生成 CodeGraph 索引
  - 上传 OSS
  - 回调 Adapter

OSS
  - 保存 codegraph-index.tar.gz
  - 保存 codegraph-status.json
  - 保存 sha256.txt
```

47 服务器当前适合第一阶段部署轻量 Worker：CPU 2 核、内存 3.4G、磁盘可用约 39G、Node/npm 已安装。它适合下载和查询索引，不适合承担多项目高并发全量索引。全量索引应放在 Codeup / 云效流水线里执行。

## 2. 多项目配置中心

后续会接入多个项目，不能写死 `jdb-school-crm`。Adapter 需要维护项目注册中心。

建议新增表：

```text
adapter_project_config
```

核心字段：

| 字段 | 含义 |
| --- | --- |
| `project_key` | 项目标识，例如 `jdb-school-crm` |
| `project_name` | 中文项目名，例如 `校CRM` |
| `repo_url` | Codeup 仓库地址 |
| `default_branch` | 默认交付分支，例如 `develop` |
| `knowledge_endpoint` | 项目知识图谱接口 |
| `knowledge_root` | 项目内知识图谱目录 |
| `codegraph_enabled` | 是否启用 CodeGraph |
| `codegraph_strategy` | `oss-artifact` / `remote-worker` / `local-only` |
| `oss_bucket` | CodeGraph 索引所在 bucket |
| `oss_prefix` | CodeGraph 索引目录前缀 |
| `yunxiao_project_id` | 云效项目 ID |
| `apifox_project_key` | Apifox 项目标识 |
| `status` | `enabled` / `disabled` |

示例：

```json
{
  "projectKey": "jdb-school-crm",
  "projectName": "校CRM",
  "repoUrl": "https://codeup.aliyun.com/.../jdb-school-crm.git",
  "defaultBranch": "develop",
  "knowledgeEndpoint": "http://xxx/white/KnowledgeGraph",
  "codegraphStrategy": "oss-artifact",
  "ossBucket": "ai-dev-artifacts",
  "ossPrefix": "codegraph/jdb-school-crm"
}
```

所有 workflow、CodeGraph、Apifox、云效绑定都必须围绕：

```text
projectKey
branchName
commitId
workflowId
```

## 3. CodeGraph + OSS 索引方案

CodeGraph 远端索引用 OSS 管理，不提交到 Git。

OSS 目录建议：

```text
oss://ai-dev-artifacts/codegraph/
  jdb-school-crm/
    develop/
      abc123/
        codegraph-index.tar.gz
        codegraph-status.json
        sha256.txt
  jdb-school-gmc/
    develop/
      def456/
        codegraph-index.tar.gz
        codegraph-status.json
        sha256.txt
```

推荐使用私有 bucket：

```text
Adapter 只保存 objectKey。
Worker 持有 OSS 只读凭证。
外部不暴露永久下载链接。
```

建议新增表：

```text
adapter_codegraph_index
```

核心字段：

| 字段 | 含义 |
| --- | --- |
| `project_key` | 项目标识 |
| `branch_name` | 分支名 |
| `commit_id` | 生成索引时的 commit |
| `storage_type` | 固定为 `oss` |
| `bucket_name` | OSS bucket |
| `object_key` | `codegraph-index.tar.gz` 路径 |
| `status_object_key` | `codegraph-status.json` 路径 |
| `sha256_object_key` | `sha256.txt` 路径 |
| `artifact_sha256` | 索引包 hash |
| `files_count` | 文件数量 |
| `nodes_count` | 节点数量 |
| `edges_count` | 边数量 |
| `index_status` | `success` / `failed` |
| `created_at` | 创建时间 |
| `expire_at` | 过期时间 |

## 4. Codeup / 云效流水线接入

develop 合并后触发流水线，流水线生成 CodeGraph 索引并上传 OSS。

流水线步骤：

```bash
npm i -g @colbymchenry/codegraph
codegraph telemetry off
codegraph index .
codegraph status . --json > codegraph-status.json
tar -czf codegraph-index.tar.gz .codegraph codegraph-status.json
sha256sum codegraph-index.tar.gz > sha256.txt

ossutil cp codegraph-index.tar.gz oss://ai-dev-artifacts/codegraph/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/
ossutil cp codegraph-status.json oss://ai-dev-artifacts/codegraph/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/
ossutil cp sha256.txt oss://ai-dev-artifacts/codegraph/${PROJECT_KEY}/${BRANCH_NAME}/${COMMIT_ID}/
```

上传完成后回调 Adapter：

```http
POST /adapter/codegraph/index-callback
Authorization: Bearer <token>
```

请求示例：

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "storageType": "oss",
  "bucketName": "ai-dev-artifacts",
  "objectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-index.tar.gz",
  "statusObjectKey": "codegraph/jdb-school-crm/develop/abc123/codegraph-status.json",
  "sha256ObjectKey": "codegraph/jdb-school-crm/develop/abc123/sha256.txt",
  "stats": {
    "files": 1642,
    "nodes": 51655,
    "edges": 84017
  }
}
```

## 5. CodeGraph Worker 设计

CodeGraph Worker 是远端代码图谱查询执行器，不是大模型，也不是业务系统。

职责：

```text
1. 根据 projectKey 找到最新索引。
2. 从 OSS 下载 codegraph-index.tar.gz。
3. 校验 sha256。
4. 解压到本地缓存。
5. 执行 codegraph explore / impact / callers / callees / node。
6. 返回结构化结果。
```

部署建议：

```text
服务目录：/opt/codegraph-worker
缓存目录：/opt/codegraph-cache
监听地址：127.0.0.1:18081
并发限制：第一阶段限制为 1
缓存上限：第一阶段 10G-20G
systemd 内存限制：1G-1.5G
```

Worker 缓存结构：

```text
/opt/codegraph-cache/
  jdb-school-crm/
    develop/
      abc123/
        .codegraph/
```

Worker 查询接口：

```http
POST /codegraph/query
```

请求：

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "mode": "impact",
  "query": "ClientServiceImpl.addClientAction"
}
```

响应：

```json
{
  "projectKey": "jdb-school-crm",
  "branchName": "develop",
  "commitId": "abc123",
  "mode": "impact",
  "symbols": [
    "ClientServiceImpl.addClientAction",
    "ClientService.addClientAction",
    "ClientController.addClientAction"
  ],
  "files": [
    "src/main/java/org/jdb/school/crm/service/impl/ClientServiceImpl.java",
    "src/main/java/org/jdb/school/crm/service/ClientService.java",
    "src/main/java/org/jdb/school/crm/controller/ClientController.java"
  ]
}
```

安全约束：

```text
Worker 不对公网开放。
外部只访问 Adapter。
Adapter 本机调用 Worker。
Worker 只持有 OSS 只读权限。
```

## 6. 知识图谱接入

每个项目可以有自己的知识图谱，Adapter 通过项目配置找到 `knowledge_endpoint`。

Adapter 新增代理接口：

```http
POST /adapter/knowledge/query
```

请求：

```json
{
  "projectKey": "jdb-school-crm",
  "question": "创建一条线索大概逻辑是什么",
  "mode": "ai"
}
```

Adapter 内部调用项目知识图谱：

```http
GET /white/KnowledgeGraph/query?question=...&mode=ai
```

查询结果写入 workflow：

```json
{
  "knowledgeContext": {
    "businessAnswer": "...",
    "developerEntrypoints": [],
    "aiPlanHints": [],
    "documents": []
  }
}
```

## 7. 端到端链路

完整链路拆解：

```text
1. 产品在钉钉提交需求。
2. Adapter 创建 workflow，状态为 CREATED。
3. Adapter 读取钉钉文档，状态推进到 DOC_READ。
4. Adapter 根据 projectKey 查询项目配置。
5. Adapter 查询项目知识图谱。
6. Adapter 查询最新 CodeGraph 索引版本。
7. Adapter 调用 CodeGraph Worker。
8. Worker 下载 OSS 索引，执行影响面分析。
9. Adapter 写入 knowledgeContext，状态推进到 KNOWLEDGE_CONTEXT_READY。
10. Codex 生成澄清问题或需求模板。
11. 有疑问则进入 CLARIFICATION_REQUIRED。
12. 需求确认后进入 REQUIREMENT_CONFIRMED。
13. Adapter 创建云效任务，进入 YUNXIAO_TASK_CREATED。
14. Codex 生成 coding spec，进入 CODING_SPEC_READY。
15. Codex coding 并提交代码，进入 CODE_SUBMITTED。
16. 合并 develop，进入 DEVELOP_MERGED。
17. 云效流水线运行，进入 PIPELINE_RUNNING。
18. 流水线成功后上传 CodeGraph 索引到 OSS，回调 Adapter，进入 CODEGRAPH_INDEXED。
19. CI 成功后上传 Apifox，进入 APIFOX_SYNCED。
20. Adapter 关闭云效任务，进入 YUNXIAO_TASK_CLOSED。
```

## 8. 状态流转设计

推荐状态机：

```text
CREATED
DOC_READ
KNOWLEDGE_CONTEXT_READY
CLARIFICATION_REQUIRED
REQUIREMENT_SPEC_READY
REQUIREMENT_CONFIRMED
YUNXIAO_TASK_CREATED
CODING_SPEC_READY
CODING_REQUESTED
CODE_SUBMITTED
MERGE_PENDING
DEVELOP_MERGED
PIPELINE_RUNNING
PIPELINE_FAILED
PIPELINE_SUCCESS
CODEGRAPH_INDEXED
APIFOX_SYNCED
YUNXIAO_TASK_CLOSED
NEEDS_HUMAN
```

关键门禁：

```text
需求未确认，不创建云效任务。
spec 未生成，不进入 coding。
代码未验证，不合并 develop。
CI 未成功，不上传 Apifox。
CodeGraph 索引未回调，不更新项目最新代码图谱版本。
Apifox 未成功，不关单。
```

## 9. Agent / Skill 介入点

确定性步骤由 Adapter 执行，不确定判断交给 Agent 或 skill。

| 阶段 | 推荐方式 |
| --- | --- |
| 读取钉钉文档 | Adapter |
| 需求清洗 | `requirements-cleanup` 或自定义 skill |
| 知识图谱查询 | `jdb-knowledge-query` skill |
| CodeGraph 影响面 | `code-impact-analyzer` skill / Worker |
| 澄清问题生成 | analyst / architect agent |
| 需求模板生成 | `requirement-template-builder` skill |
| spec 生成 | `spec-coding-planner` skill |
| Java 编码 | `java-api-impl`、`java-coding-standards` |
| SQL 检查 | `sql-review` |
| 代码 review | `code-review` / verifier |
| CI 回调 | Adapter |
| Apifox 上传 | Adapter |
| 关单 | Adapter |

优先固化的自定义 skill：

```text
jdb-knowledge-query
code-impact-analyzer
requirement-template-builder
spec-coding-planner
```

## 10. 一期方案

一期目标：

```text
跑通多项目 + 知识上下文 + CodeGraph OSS 索引 + Worker 查询，不做全自动关单。
```

一期范围：

1. 新增 `adapter_project_config`。
2. 新增 `adapter_codegraph_index`。
3. 新增 `/adapter/knowledge/query`。
4. 新增 `/adapter/codegraph/index-callback`。
5. Codeup 流水线生成 CodeGraph 索引。
6. CodeGraph 索引上传 OSS。
7. Adapter 记录索引版本。
8. 在 47 服务器部署轻量 CodeGraph Worker。
9. Worker 支持从 OSS 下载、校验、解压、缓存、查询。
10. workflow 保存 `knowledgeContext`。
11. Codex 根据上下文生成需求模板和 coding spec。

一期状态流：

```text
CREATED
DOC_READ
KNOWLEDGE_CONTEXT_READY
CLARIFICATION_REQUIRED
REQUIREMENT_SPEC_READY
REQUIREMENT_CONFIRMED
YUNXIAO_TASK_CREATED
CODING_SPEC_READY
CODING_REQUESTED
CODE_SUBMITTED
```

一期验收标准：

```text
一个项目能注册到 Adapter。
一次 develop 合并能生成 CodeGraph OSS 索引。
Adapter 能记录索引版本。
47 Worker 能下载 OSS 索引并查询影响面。
一个需求能查询知识图谱。
一个需求能拿到 CodeGraph 影响面。
Codex 能基于上下文生成需求模板和 spec。
```

## 11. 二期方案

二期目标：

```text
打通代码提交后的交付闭环。
```

二期范围：

1. 提交信息强制带 `workflowId`、`yunxiaoTaskId`、`requirementVersion`、`projectKey`。
2. 合并 develop 后触发 CI/CD。
3. 云效流水线回调 Adapter。
4. CI 成功后上传 Apifox。
5. Apifox 成功后关闭云效任务。
6. CI 失败进入 `PIPELINE_FAILED`。
7. 可重试失败回到 `CODING_REQUESTED`。
8. 不可自动处理进入 `NEEDS_HUMAN`。

二期状态流：

```text
CODE_SUBMITTED
MERGE_PENDING
DEVELOP_MERGED
PIPELINE_RUNNING
PIPELINE_FAILED
PIPELINE_SUCCESS
CODEGRAPH_INDEXED
APIFOX_SYNCED
YUNXIAO_TASK_CLOSED
```

二期验收标准：

```text
develop 合并能被 Adapter 感知。
CI 成功能推进 workflow。
CI 失败不会误关单。
CodeGraph 新索引能上传 OSS 并回调。
Apifox 上传结果能记录。
云效任务能自动关闭。
所有动作都有审计记录。
```

## 12. 最终形态

最终形态是一个多项目 AI 研发交付平台：

```text
产品需求
  -> Adapter workflow
  -> 知识图谱业务上下文
  -> CodeGraph OSS 索引影响面
  -> Codex 澄清
  -> 需求模板
  -> 云效任务
  -> spec coding
  -> commit + workflowId + 任务号
  -> merge develop
  -> CI/CD
  -> CodeGraph 新索引上传 OSS
  -> Apifox
  -> 关单
  -> 审计留痕
```

多项目只需要配置：

```text
项目仓库
默认分支
知识图谱地址
OSS bucket/prefix
CodeGraph 策略
云效项目
Apifox 项目
```

## 13. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| CodeGraph 索引过期 | 每次上下文记录 `branchName`、`commitId`、`indexVersion` |
| 47 服务器资源不足 | 只做下载和查询，全量索引放流水线；Worker 限并发和缓存 |
| OSS 索引泄露 | 私有 bucket，Worker 持有只读凭证，不暴露永久 URL |
| 需求未澄清就建任务 | 增加 `REQUIREMENT_CONFIRMED` 门禁 |
| spec 和 coding 混在一起 | 增加 `CODING_SPEC_READY` 状态 |
| CI 失败误关单 | 只有 `PIPELINE_SUCCESS` + `APIFOX_SYNCED` 才能关单 |
| 多项目配置混乱 | 所有流程以 `projectKey` 为主键 |
| Agent 绕过流程 | 所有结果必须回写 Adapter workflow |
| Adapter 负载过重 | CodeGraph 查询拆到 Worker，索引拆到 CI |

## 三、总：最终结论

重新整合后的推荐路线是：

```text
Adapter + 多项目配置
+ 知识图谱代理
+ CodeGraph CI 索引
+ OSS 产物存储
+ 47 轻量 CodeGraph Worker
+ workflow 状态机
+ Codex spec coding
+ 云效 / CI / Apifox / 关单
```

落地优先级：

```text
第一优先级：项目配置中心
第二优先级：CodeGraph OSS 索引链路
第三优先级：47 CodeGraph Worker 查询链路
第四优先级：知识上下文写入 workflow
第五优先级：需求模板和 spec coding
第六优先级：CI / Apifox / 关单自动化
```

一期先在 47 上部署轻量 Worker 是可行的，但它只负责索引下载、缓存和查询；全量索引仍应由 Codeup / 云效流水线生成并上传 OSS。这样既能支持多项目，也能保证每次需求评估都有明确的代码版本、业务上下文、影响面和审计链路。
