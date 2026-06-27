# AI研发闭环与多项目CodeGraph接入方案

## 一、总：整体目标

本方案目标是把 `adapter-mvp` 建成 AI 研发交付的中转层，用它串起产品需求、知识图谱、CodeGraph、云效、Codex、CI/CD、Apifox 和关单流程。

最终形态不是让 Adapter 自己做推理和编码，而是让 Adapter 负责流程、状态、配置、鉴权、审计和外部系统调用；业务理解、代码影响面分析和编码分别交给知识图谱、CodeGraph 和 Codex/Agent。

整体闭环如下：

```text
产品需求
  -> Adapter 创建 workflow
  -> 读取需求文档
  -> 结合知识图谱和 CodeGraph 做澄清
  -> 生成标准需求模板
  -> 确认后创建云效任务
  -> 生成 spec
  -> Codex coding
  -> 提交代码并带任务号/版本号
  -> 合并 develop
  -> 触发 CI/CD
  -> Apifox 接口上传
  -> 关单
```

职责边界：

| 组件 | 职责 |
| --- | --- |
| Adapter | workflow 状态机、多项目配置、鉴权、审计、外部 API、回调推进 |
| 知识图谱 | 业务视图、研发视图、AI 视图、历史逻辑、业务问答 |
| CodeGraph | 代码入口、调用链、影响面、改动风险 |
| Codex / Agent | 需求澄清、需求模板、spec、coding、review、git 操作 |
| 云效 | 任务管理、流水线、回调 |
| Apifox | 接口资产同步 |

核心原则：

```text
Adapter 管流程，不做大脑。
Agent 管理解，不绕过状态机。
CodeGraph 管代码影响面，不替代业务知识图谱。
```

## 二、分：具体方案

## 1. 总体架构

```text
Adapter
  - workflow 状态机
  - project registry
  - codegraph index registry
  - audit
  - DingTalk / Yunxiao / Apifox API

Knowledge Graph
  - business-view
  - dev-view
  - ai-view
  - question-map
  - knowledge-manifest
  - codegraph-map

CodeGraph
  - per project index
  - per branch/commit version
  - impact / callers / callees / node / explore

Codex / Agent
  - requirement clarification
  - requirement template
  - spec generation
  - coding
  - review

Codeup / Yunxiao
  - repo
  - task
  - CI/CD
  - callback
```

Adapter 是流程中枢和安全边界，不直接承担复杂推理。所有不确定判断都应该产出结构化上下文，再由状态机决定下一步。

## 2. 多项目接入设计

后续需要支持多个项目，不能写死 `jdb-school-crm`。Adapter 需要维护项目注册中心。

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
| `codegraph_strategy` | `ci-artifact` / `remote-worker` / `local-only` |
| `yunxiao_project_id` | 云效项目 ID |
| `apifox_project_key` | Apifox 项目标识 |
| `status` | `enabled` / `disabled` |

workflow、CodeGraph、Apifox、云效绑定都必须围绕以下字段：

```text
projectKey
branchName
commitId
workflowId
```

避免使用硬编码路径或单项目逻辑。

## 3. CodeGraph 接入设计

CodeGraph 不建议提交到 Git 仓库，也不建议直接把 `.codegraph/codegraph.db` 放进 Codeup 仓库。

推荐方式是由 Codeup 流水线生成索引产物：

```text
Codeup push/merge develop
  -> 触发流水线
  -> checkout 当前 commit
  -> 安装 CodeGraph
  -> 执行 codegraph index
  -> 打包 .codegraph
  -> 上传为流水线 artifact
  -> 回调 Adapter
  -> Adapter 记录索引版本
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
| `artifact_url` | 索引产物地址 |
| `index_status` | `success` / `failed` |
| `files_count` | 文件数量 |
| `nodes_count` | 节点数量 |
| `edges_count` | 边数量 |
| `created_at` | 索引生成时间 |

流水线示例：

```bash
npm i -g @colbymchenry/codegraph
codegraph telemetry off
codegraph index .
codegraph status . > codegraph-status.txt
tar -czf codegraph-index.tar.gz .codegraph codegraph-status.txt
```

回调 Adapter：

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
  "artifactUrl": "https://codeup.example/artifacts/codegraph-index.tar.gz",
  "stats": {
    "files": 1642,
    "nodes": 51655,
    "edges": 84017
  }
}
```

远期可以拆出独立 CodeGraph Worker：

```text
Adapter API：流程、鉴权、审计
CodeGraph Worker：拉代码、建索引、查询影响面
Codeup CI：合并后触发索引更新
```

## 4. 状态流转设计

建议 workflow 状态机如下：

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
APIFOX_SYNCED
YUNXIAO_TASK_CLOSED
NEEDS_HUMAN
```

状态说明：

| 状态 | 含义 |
| --- | --- |
| `CREATED` | workflow 已创建 |
| `DOC_READ` | 已读取产品需求文档 |
| `KNOWLEDGE_CONTEXT_READY` | 已结合知识图谱和 CodeGraph 生成上下文 |
| `CLARIFICATION_REQUIRED` | 需求有疑问，需要产品确认 |
| `REQUIREMENT_SPEC_READY` | 已生成标准需求模板 |
| `REQUIREMENT_CONFIRMED` | 需求模板已确认 |
| `YUNXIAO_TASK_CREATED` | 云效任务已创建 |
| `CODING_SPEC_READY` | 技术 spec 已生成 |
| `CODING_REQUESTED` | 可以开始编码 |
| `CODE_SUBMITTED` | 代码已提交 |
| `MERGE_PENDING` | 等待合并 develop |
| `DEVELOP_MERGED` | 已合并 develop |
| `PIPELINE_RUNNING` | CI/CD 运行中 |
| `PIPELINE_FAILED` | CI/CD 失败 |
| `PIPELINE_SUCCESS` | CI/CD 成功 |
| `APIFOX_SYNCED` | Apifox 接口已同步 |
| `YUNXIAO_TASK_CLOSED` | 云效任务已关闭 |
| `NEEDS_HUMAN` | 等待人工处理 |

关键门禁：

```text
需求未确认，不创建云效任务。
spec 未生成，不进入 coding。
代码未验证，不合并 develop。
CI 未成功，不上传 Apifox。
Apifox 未成功，不关单。
```

## 5. 知识上下文结构

Adapter workflow 需要保存结构化上下文，建议写入 `context_json` 或 `extra.knowledgeContext`。

示例：

```json
{
  "knowledgeContext": {
    "projectKey": "jdb-school-crm",
    "question": "线索创建增加校验",
    "businessView": {
      "answer": "线索创建会完成客户主记录、跟进、学校适配、家长、意向课程、负责人和状态记录。",
      "documents": [
        "doc/knowledge-graph/business-view/Client/addClientAction.md"
      ]
    },
    "developerView": {
      "entrypoints": [
        "ClientController#addClientAction",
        "ClientServiceImpl#addClientAction"
      ],
      "tables": [
        "crm_client",
        "crm_client_track",
        "crm_client_schoolenter"
      ]
    },
    "codegraph": {
      "branchName": "develop",
      "commitId": "abc123",
      "indexVersion": "abc123",
      "symbols": [
        "ClientServiceImpl.addClientAction"
      ],
      "impact": [
        "ClientServiceImpl#addClientAction",
        "ClientService#addClientAction",
        "ClientController#addClientAction"
      ]
    },
    "risks": [
      "重复校验变更可能影响手工创建和外部渠道创建口径",
      "负责人和分配日志必须成对落库"
    ]
  }
}
```

## 6. Agent / Skill 介入点

不是所有步骤都需要 Agent。确定性步骤由 Adapter 执行，不确定判断交给 Agent 或 skill。

| 阶段 | 推荐方式 |
| --- | --- |
| 读取钉钉文档 | Adapter |
| 需求清洗 | `requirements-cleanup` 或自定义 skill |
| 知识图谱查询 | `jdb-knowledge-query` skill |
| CodeGraph 影响面 | `code-impact-analyzer` skill |
| 澄清问题生成 | analyst / architect agent |
| 需求模板生成 | `requirement-template-builder` skill |
| spec 生成 | `spec-coding-planner` skill |
| Java 编码 | `java-api-impl`、`java-coding-standards` |
| SQL 检查 | `sql-review` |
| 代码 review | `code-review` / verifier |
| CI 回调 | Adapter |
| Apifox 上传 | Adapter |
| 关单 | Adapter |

第一批建议固化的自定义 skill：

```text
jdb-knowledge-query
code-impact-analyzer
requirement-template-builder
spec-coding-planner
```

## 7. 一期方案

一期目标：

```text
先跑通需求到 spec / coding 上下文，不急着全自动关单。
```

一期范围：

1. 新增多项目配置。
2. 新增 CodeGraph 索引版本记录。
3. Codeup 流水线生成 CodeGraph artifact。
4. Adapter 接收 CodeGraph index callback。
5. Adapter 支持知识图谱查询代理。
6. workflow 保存 `knowledgeContext`。
7. Codex 根据 `knowledgeContext` 生成需求模板。
8. 人工确认后创建云效任务。
9. Codex 生成 coding spec。
10. Codex coding 后提交结果回写 Adapter。

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
一个真实需求可以从钉钉文档进入 Adapter。
能生成需求模板。
能结合知识图谱和 CodeGraph 输出影响面。
能创建云效任务。
能生成 coding spec。
能记录分支、commit、测试结果。
```

## 8. 二期方案

二期目标：

```text
把代码提交后的交付链路接完整。
```

二期范围：

1. 代码提交信息强制带任务号、workflowId、版本号。
2. 合并 develop 后触发 CI/CD。
3. 云效流水线回调 Adapter。
4. CI 成功后触发 Apifox 上传。
5. Apifox 成功后关闭云效任务。
6. CI 失败时回到 `PIPELINE_FAILED`。
7. 可重试需求回到 `CODING_REQUESTED`。
8. 不可自动处理时进入 `NEEDS_HUMAN`。

二期状态流：

```text
CODE_SUBMITTED
MERGE_PENDING
DEVELOP_MERGED
PIPELINE_RUNNING
PIPELINE_FAILED
PIPELINE_SUCCESS
APIFOX_SYNCED
YUNXIAO_TASK_CLOSED
```

二期验收标准：

```text
develop 合并能被 Adapter 感知。
CI 成功能推进 workflow。
Apifox 上传成功能记录。
云效任务能自动关闭。
CI 失败不会误关单。
所有动作都有审计记录。
```

## 9. 最终形态

最终形态是一个多项目 AI 研发交付平台：

```text
产品提出需求
  -> Adapter 读取需求
  -> 知识图谱判断业务逻辑
  -> CodeGraph 判断代码影响面
  -> Codex 生成澄清问题
  -> 产品确认需求模板
  -> Adapter 创建云效任务
  -> Codex 生成 spec 并编码
  -> 代码提交并带任务号
  -> 合并 develop
  -> 云效 CI/CD
  -> Apifox 同步
  -> Adapter 关单
  -> 审计留痕
```

每个项目只需要补项目配置：

```text
项目仓库
知识图谱地址
CodeGraph 索引策略
云效项目
Apifox 项目
默认分支
```

## 10. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| CodeGraph 索引过期 | 每次上下文记录 `branchName`、`commitId`、`indexVersion` |
| 需求未澄清就建任务 | 增加 `REQUIREMENT_CONFIRMED` 门禁 |
| spec 和 coding 混在一起 | 增加 `CODING_SPEC_READY` 状态 |
| CI 失败误关单 | 只有 `PIPELINE_SUCCESS` + `APIFOX_SYNCED` 才能关单 |
| 多项目配置混乱 | 所有流程以 `projectKey` 为主键 |
| Agent 绕过流程 | 所有结果必须回写 Adapter workflow |
| Adapter 负载过重 | CodeGraph 索引拆到 CI 或 Worker |

## 三、总：最终结论

该方案可以形成可持续的 AI 研发闭环，但必须分阶段实施。

推荐顺序：

```text
一期：多项目配置 + CodeGraph 索引记录 + 知识上下文 + 需求模板 + spec coding
二期：develop 合并 + CI 回调 + Apifox 上传 + 自动关单
最终：多项目统一 AI 研发交付闭环
```

最先要打稳的不是自动编码，而是：

```text
项目配置中心
CodeGraph 远端索引版本
知识图谱上下文写入 workflow
```

这三件事稳定后，后续自动 coding、CI、Apifox 和关单才不会混乱。

