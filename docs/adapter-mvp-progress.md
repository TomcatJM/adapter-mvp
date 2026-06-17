# Adapter MVP 当前进度说明

## 1. 当前定位

`adapter-mvp` 目前已经不是单纯的 SSH 小工具，而是一个正在成型的交付集成服务。

当前更准确的定位是：

```text
Adapter MVP = 工具适配层 + 审计状态层 + 云效/钉钉/Apifox 集成入口
```

目标形态是：

```text
Adapter MVP = Workflow Orchestrator + Tool Adapter
```

也就是：Codex 负责理解需求和写代码，`adapter-mvp` 负责读钉钉、接云效、同步 Apifox、记录状态和审计。

## 2. 已完成能力

### 2.1 远端部署

已部署到远端服务器：

```text
公网地址：http://47.116.102.238:18080
应用目录：/opt/adapter-mvp
systemd 服务：adapter-mvp
环境变量：/etc/adapter-mvp/adapter-mvp.env
审计日志：/opt/adapter-mvp/logs/audit.jsonl
```

已具备：

- `/health` 探活接口。
- systemd 托管启动。
- 远端状态、重启、日志查看脚本。
- 密钥放在远端 env 和本地 `secrets/`，未放入代码仓库。

### 2.2 鉴权和安全门禁

已完成：

- 业务接口使用 `Authorization: Bearer <ADAPTER_API_TOKEN>`。
- `/health` 不需要 token。
- `/adapter/execute` 必须带 `approvalId` 或 `approved=true`。
- 云效 execute 回调同样需要审批参数。
- 审计和响应中避免输出密码、token、私钥。

当前安全策略是对的：默认 preview，execute 必须显式审批。

### 2.3 Adapter Preview / Execute / Status / Audit

已完成统一 Adapter API：

```http
POST /adapter/preview
POST /adapter/execute
GET  /adapter/status/{task_id}
GET  /adapter/audit/{task_id}
```

当前已支持动作：

```text
ssh.check_connectivity
```

用途：

- preview：只预览动作，不执行真实远端操作。
- execute：执行动作，但必须经过审批。
- status：查询执行结果。
- audit：查询审计事件。

### 2.4 MySQL 状态和审计持久化

已完成两张基础表：

```text
adapter_status
adapter_audit
```

能力：

- `adapter_status` 保存任务执行结果。
- `adapter_audit` 保存 preview、execute、status、pipeline failure、apifox import 等事件。
- 审计同时写文件和 MySQL。
- 服务重启后，状态可从 MySQL 恢复。

这部分已经是后续 workflow 的基础账本。

### 2.5 钉钉 / Alidocs 文档读取

已完成接口：

```http
POST /adapter/dingtalk/read
POST /adapter/dingtalk/config
POST /adapter/dingtalk/resolve-operator
```

当前能力：

- 通过 Adapter 托管的钉钉 OpenAPI 配置读取 Alidocs。
- 支持从 URL 提取 `nodeId`。
- 支持 `adoc` 文档。
- 支持 `axls` 表格，默认读取 `A1:J50`。
- 钉钉应用凭据和文档 endpoint 模板拆成两类配置。
- access_token 有缓存。
- 支持 operator 解析。

相关表：

```text
adapter_dingtalk_app
adapter_dingtalk_doc_config
adapter_dingtalk_app_config  # 旧兼容表
```

这部分已经可以作为 Codex 读取钉钉需求文档的工具入口。

### 2.6 云效回调接入

当前云效只能算“部分接入”，不能算完整打通。

已实现的服务端入口：

```http
POST /callbacks/yunxiao/task
POST /callbacks/yunxiao/pipeline-failure
POST /callbacks/yunxiao/flow-event
POST /callbacks/yunxiao/flow-event/public
```

已具备的能力：

- 云效任务回调可触发 Adapter preview。
- 云效任务回调可在带审批时触发 execute。
- 云效流水线失败可调用 `pipeline_agent.py` 做规则分析。
- 云效通用 flow event 可以识别成功、失败、取消等状态。
- public flow event 路由已保留给云效无法带认证头的场景。

已经验证过的部分：

- 云效 Preview 节点调用成功。
- 云效 Audit 节点能查到同一个 `TASK_ID` 的审计记录。
- Preview / Audit 拆分节点已验证成功。

尚未完整打通的部分：

- Adapter 主动创建云效工作项。
- Adapter 主动关闭云效工作项。
- 云效工作项状态和 workflow 状态双向绑定。
- 云效流水线成功后精确匹配某个 workflow 实例。
- 云效成功后自动执行“Apifox 同步 -> 云效关单”的闭环。

所以当前结论是：云效到 Adapter 的低风险 Preview/Audit 链路已验证，云效工作项和完整交付闭环还没打通。

### 2.7 流水线失败分析

已有 `app/pipeline_agent.py`，当前是规则型分析器。

可识别：

- 编译失败。
- 测试失败。
- 依赖解析失败。
- Adapter 执行失败。
- 质量门禁失败。

它现在还不是完整 Agent，更像一个轻量规则分析器。这个阶段够用，后面可以升级成更智能的失败分析 Agent。

### 2.8 Apifox 自动导入

已完成核心逻辑：

- 云效 flow event 成功时，可触发 `maybe_import_from_flow_event`。
- 可按 pipelineId / projectName / repo / 环境变量解析 Apifox 项目。
- 支持数据库配置：

```text
adapter_apifox_project_config
adapter_apifox_pipeline_config
```

已支持：

- 拉取上游 OpenAPI。
- 处理被 JSON 字符串或 base64 包裹的 OpenAPI 返回。
- 校验 OpenAPI 基础结构。
- 去掉项目名前缀路径。
- 通过 Adapter 暴露清洗后的 OpenAPI：

```http
GET /adapter/openapi/{project_name}
```

注意：Apifox 自动导入是否真的执行，受环境变量控制：

```text
APIFOX_AUTO_IMPORT=true
APIFOX_ACCESS_TOKEN=...
APIFOX_PROJECT_ID=...
```

没有配置完整时，会返回 skipped，不会强行导入。

### 2.9 测试覆盖

当前已有测试：

```text
tests/test_dingtalk_split_config_mapping.py
tests/test_dingtalk_operator_resolution.py
tests/test_public_flow_event_route.py
tests/test_apifox_openapi_wrapped_response.py
```

覆盖点包括：

- 钉钉配置拆分映射。
- 钉钉 operator 解析。
- flow event public/private 路由安全边界。
- Apifox OpenAPI 包裹响应解析。

## 3. 当前大概流程

### 3.1 已经跑通的实际流程

```text
云效流水线 / 人工调用
  -> /callbacks/yunxiao/task
  -> Adapter preview
  -> 写 audit
  -> /adapter/audit/{task_id} 查询
```

这条链路已验证，但它只代表云效能调用 Adapter 并完成 Preview/Audit，不代表云效任务创建、流水线成功闭环、关单已经完成。

### 3.2 当前已接入 workflow P0 的钉钉需求流程

```text
Codex / 调用方
  -> /workflow/start
  -> /workflow/{id}/advance
  -> Adapter 读取钉钉需求文档
  -> 保存到 workflow context
  -> Codex 解析需求
  -> /workflow/{id}/requirement
```

这条链路已完成 P0：钉钉读取结果会进入 `adapter_workflow_instance.context_json`，并写入 `adapter_workflow_event`。

### 3.3 当前云效成功后同步 Apifox 的流程

```text
云效 flow event 成功
  -> /callbacks/yunxiao/flow-event 或 /public
  -> maybe_import_from_flow_event
  -> 解析 pipeline/project/openapi/apifox 配置
  -> 可选导入 Apifox
  -> 写 apifox_import audit
```

这段已经有实现，但目前还是事件级工具链，不是完整业务闭环：

- 已能根据云效成功事件尝试解析项目和 Apifox 配置。
- 已能在配置完整时触发 Apifox 导入。
- 还没有和 `adapter_workflow_instance` 绑定。
- 还不能在 Apifox 成功后自动关闭云效工作项。
- 也还没有用 workflow 事件表记录 `PIPELINE_SUCCESS -> APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED`。

### 3.4 目标完整流程

```text
钉钉需求文档
  -> adapter-mvp 创建 workflow
  -> adapter-mvp 读取钉钉文档
  -> Codex 解析需求
  -> adapter-mvp 创建云效任务
  -> Codex coding
  -> Codex 提交 branch/commit/MR
  -> 云效流水线运行
  -> 云效成功回调 adapter-mvp
  -> adapter-mvp 同步 API 到 Apifox
  -> adapter-mvp 关闭云效任务
```

这条完整链路还没有全部实现，当前已经完成的是其中的工具和回调底座。

## 4. 尚未完成的能力

### 4.1 Workflow P0 已实现，后续状态机仍需扩展

已完成设计文档：

```text
docs/workflow-orchestrator-design.md
```

当前已实现 P0：

- `adapter_workflow_instance`
- `adapter_workflow_event`
- `/workflow/start`
- `/workflow/{id}`
- `/workflow/{id}/advance`
- `/workflow/{id}/requirement`
- `/workflow/{id}/coding-result`

其中 `/workflow/{id}/advance` 已支持从 `CREATED` 读取钉钉文档并推进到 `DOC_READ`；读取失败会记录 `doc_read_failed` 事件和 `last_error`，保留在 `CREATED` 便于修复配置后重试。

后续仍需补：

- `/workflow/{id}/retry`
- `/workflow/{id}/resolve`
- 更完整的状态迁移约束。

### 4.2 钉钉需求到 workflow 的基础绑定已完成

当前已支持：

- `/workflow/start` 自动创建 workflow 实例。
- 保存 `dingtalkUrl`、`nodeId` 到 `context_json`。
- `/workflow/{id}/advance` 读取钉钉文档。
- 将读取结果摘要保存到 `context_json.dingtalk.read`。
- 写入 `doc_read` / `doc_read_failed` 事件。

后续还需要给 Codex 返回更标准化的 `codingRequest`。

### 4.3 需求解析 Agent 未固化

现在依赖 Codex 对话内解析，没有统一结构化输出协议。

需要补：

```text
summary
acceptanceCriteria
affectedRepos
apiChanges
testScope
risk
openQuestions
```

然后由 Codex 调用：

```http
POST /workflow/{workflow_id}/requirement
```

### 4.4 云效工作项创建/关闭未实现

现在已有云效回调入口，也有 `scripts/yunxiao_workitem_writeback.sh` 这种脚本级尝试，但还没有产品化的云效工作项 adapter。

需要补：

- 云效 OpenAPI 配置。
- 创建主任务接口。
- 更新任务状态接口。
- 关闭任务接口。
- 评论/回写接口。
- 统一封装到服务端，而不是只靠云效 Shell 脚本。
- 将云效工作项 ID 写入 workflow 实例。

### 4.5 Coding 结果回传 P0 已实现

当前已有固定入口：

```http
POST /workflow/{workflow_id}/coding-result
```

保存：

- 分支名。
- commitId。
- MR 地址。
- 变更摘要。
- 测试结果。

状态会推进到 `CODE_SUBMITTED`。后续还需要接云效流水线运行状态。

### 4.6 流水线成功回调与 workflow 未绑定

现在成功 flow event 可以触发 Apifox 导入，但还没有：

- 根据 `workflowId` 或 `yunxiao_task_id` 找到 workflow。
- 将状态推进到 `PIPELINE_SUCCESS`。
- 再推进到 `APIFOX_SYNCED`。
- 最后推进到 `YUNXIAO_TASK_CLOSED`。

### 4.7 Apifox 同步后关闭云效任务未完成

Apifox 导入逻辑已有，但导入成功后还没有自动关闭云效任务。

需要等云效工作项 adapter 完成后接上。

### 4.8 失败恢复机制未完成

已有失败分析，但还没有完整恢复链路：

- `PIPELINE_FAILED` 状态。
- 自动生成修复请求。
- `NEEDS_HUMAN` 人工处理。
- 手动 retry / resolve。
- 最大重试次数控制。

### 4.9 Codex 自动调用 Adapter 的入口未固化

现在 Codex 可以手动调用 Adapter，但还没有形成稳定入口：

- Codex Skill。
- MCP tool。
- 或 Codex plugin。

建议先做 Skill 或 MCP tool，不急着做复杂 plugin。

## 5. 建议下一步怎么做

### Step 1：先实现被动 workflow 账本（已完成 P0）

目标：先让每个需求有一条主线记录。

新增：

- `adapter_workflow_instance`
- `adapter_workflow_event`
- `/workflow/start`
- `/workflow/{id}`
- `/workflow/{id}/requirement`
- `/workflow/{id}/coding-result`

这一阶段不要自动创建云效任务，也不要自动关单。当前已做到可记录、可查询、可追踪。

### Step 2：把钉钉读取接入 workflow（已完成 P0）

目标：`/workflow/start` 后可读取钉钉文档并推进到 `DOC_READ`。

实现：

- `/workflow/{id}/advance` 在 `CREATED` 状态调用现有 `read_dingtalk_doc`。
- 将返回结果摘要保存到 `context_json`。
- 事件表写入 `doc_read`。

### Step 3：固化 Codex 需求解析协议（已完成 P0，待增强）

目标：Codex 不只是“读懂”，还要把结果以固定 JSON 提交回 Adapter。

实现：

- 定义 `/workflow/{id}/requirement` 入参。
- 保存结构化需求。
- 状态推进到 `REQUIREMENT_PARSED`。
- 返回下一步建议，例如是否创建云效任务。

### Step 4：实现云效工作项 adapter

目标：结构化需求确认后，自动创建云效任务。

实现：

- 云效创建任务。
- 云效评论/回写。
- 云效关闭任务。
- 状态从 `REQUIREMENT_PARSED` 推进到 `YUNXIAO_TASK_CREATED`。

### Step 5：接入 Coding 结果（已完成 P0）

目标：Codex 完成编码后，结果可进入 workflow。

实现：

- `/workflow/{id}/coding-result`
- 保存 branch/commit/MR/test summary。
- 状态推进到 `CODE_SUBMITTED`。

### Step 6：把流水线成功回调接进 workflow

目标：云效成功后，自动推进发布尾段。

实现：

- 新增或扩展成功 callback。
- 匹配 workflow。
- 状态推进到 `PIPELINE_SUCCESS`。
- 调用 Apifox 同步。
- 成功后推进到 `APIFOX_SYNCED`。

### Step 7：Apifox 成功后关闭云效任务

目标：完整闭环。

实现：

- Apifox 导入成功后调用云效关闭任务接口。
- 状态推进到 `YUNXIAO_TASK_CLOSED`。
- 写最终事件。

## 6. 推荐优先级

| 优先级 | 事项 | 原因 |
| --- | --- | --- |
| Done | workflow 表和基础接口 | P0 已落地 |
| Done | 钉钉读取接入 workflow | P0 已落地 |
| Done | Codex 结构化需求提交 | P0 已落地，后续增强协议 |
| Done | Coding 结果提交 | P0 已落地 |
| P1 | 流水线成功绑定 workflow | 接上发布尾段 |
| P2 | 云效任务创建/关闭 | 依赖云效 OpenAPI 配置 |
| P2 | 失败恢复和人工处理 | 提升稳定性 |
| P3 | Skill/MCP/Plugin 化 | 让 Codex 调用更顺滑 |

## 7. 当前结论

`adapter-mvp` 现在已经完成了“工具底座”和“部分事件自动化”：

- 能被云效调用。
- 能读钉钉文档。
- 能接流水线事件。
- 能分析失败。
- 能尝试同步 Apifox。
- 能记录审计和状态。

但它还不是完整的交付 Workflow Orchestrator。当前最关键的下一步，是实现 workflow 实例表、事件表和基础接口，让每个需求从钉钉文档开始就有一条可追踪的主线。

先有账本，再自动推进。这个顺序最稳。

## 8. 云效相关任务拆分

云效这块不要作为一个大任务一次性做完，建议拆成三个可并行但边界清晰的任务：

| 任务 | 文档 | 输入状态 | 输出状态 | 说明 |
| --- | --- | --- | --- | --- |
| 云效工作项创建 | `docs/yunxiao-workitem-create-task.md` | `REQUIREMENT_PARSED` | `YUNXIAO_TASK_CREATED` / `CODING_REQUESTED` | 只负责主动创建云效主工作项 |
| 云效流水线打通 | `docs/yunxiao-pipeline-integration-task.md` | `CODE_SUBMITTED` | `PIPELINE_SUCCESS` / `PIPELINE_FAILED` / `APIFOX_SYNCED` | 只负责流水线事件绑定 workflow 和 Apifox 交接 |
| 云效工作项关闭/回写 | `docs/yunxiao-workitem-close-task.md` | `APIFOX_SYNCED` | `YUNXIAO_TASK_CLOSED` | 只负责 Apifox 成功后的云效回写和关单 |

推荐实施顺序：

```text
P0 workflow 账本
  -> 云效流水线绑定 workflow
  -> 云效工作项创建
  -> 云效工作项关闭/回写
```

如果要并行处理，流水线绑定和工作项创建可以同时做；工作项关闭最好等 Apifox 成功写入 workflow 后再接。
