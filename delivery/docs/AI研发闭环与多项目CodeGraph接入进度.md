# AI研发闭环与多项目CodeGraph接入进度

## 1. 总体进度

| 模块 | 当前状态 | 说明 | 下一步 |
| --- | --- | --- | --- |
| 方案文档 | 已完成 | 已形成总分总方案，覆盖多项目、OSS、CodeGraph Worker、状态流转、一期/二期 | 后续随实现同步维护 |
| Adapter 基础服务 | 已完成 | 47 服务器上的 `adapter-mvp` 正常运行，已有鉴权、审计、workflow、钉钉、云效、Apifox 相关基础能力 | 新增知识图谱和 CodeGraph 相关接口 |
| 钉钉需求读取 | 已完成 | 已有 `/adapter/dingtalk/read` 和 workflow 读取链路 | 接入需求模板生成 |
| Workflow 账本 | 部分完成 | 已有 workflow 创建、推进、需求提交、编码结果提交、流水线回调等基础状态 | 扩展知识上下文和 CodeGraph 状态 |
| 云效任务创建 | 部分完成 | 已有云效工作项创建相关能力和配置文档 | 与需求模板确认状态绑定 |
| 云效流水线回调 | 部分完成 | 已有流水线事件回调、成功/失败推进、Apifox 触发基础链路 | 补 CodeGraph 索引回调状态 |
| Apifox 同步 | 部分完成 | 已有 OpenAPI 清洗、Apifox 同步相关链路 | 绑定到 CI 成功后的正式关单前置条件 |
| 多项目配置中心 | 未开始 | 当前更多是云效/Apifox维度配置，尚未抽象为统一 `adapter_project_config` | 一期优先建设 |
| 知识图谱代理接口 | 未开始 | 校 CRM 已有知识图谱接口，但 Adapter 尚未代理 | 新增 `/adapter/knowledge/query` |
| CodeGraph 本地验证 | 已完成 | `jdb-school-crm` 本地已生成 CodeGraph 索引，并验证能查线索创建影响面 | 转为远端 OSS 索引链路 |
| CodeGraph OSS 索引 | 未开始 | 尚未在 Codeup / 云效流水线生成并上传 OSS | 一期建设流水线索引脚本 |
| CodeGraph Worker | 未开始 | 已确认 47 适合部署轻量 Worker，但尚未实现 | 一期部署 `127.0.0.1:18081` 轻量查询服务 |
| Agent / Skill 固化 | 未开始 | 目前是方案层设计，尚未形成专用 skill | 先做 `jdb-knowledge-query` 和 `code-impact-analyzer` |
| 自动合并 develop | 未开始 | 当前仍由 Codex/人工执行 git 流程 | 二期再接入 |
| 自动关单 | 部分完成 | 已有云效关单能力，但尚未和 AI 研发闭环完整绑定 | 二期绑定 CI + Apifox 成功条件 |

## 2. 一期进度

一期目标：

```text
跑通多项目 + 知识上下文 + CodeGraph OSS 索引 + Worker 查询，不做全自动关单。
```

| 序号 | 事项 | 状态 | 当前证据 | 下一步 |
| --- | --- | --- | --- | --- |
| 1 | 新增多项目配置 `adapter_project_config` | 未开始 | 方案已定义字段 | 建表并补配置接口 |
| 2 | 新增 CodeGraph 索引表 `adapter_codegraph_index` | 未开始 | 方案已定义字段 | 建表并补回调接口 |
| 3 | 新增 `/adapter/knowledge/query` | 未开始 | 校 CRM 已有 `/white/KnowledgeGraph/query` | Adapter 增加代理接口 |
| 4 | 新增 `/adapter/codegraph/index-callback` | 未开始 | 方案已定义请求体 | Adapter 增加回调接口和入库 |
| 5 | Codeup / 云效流水线生成 CodeGraph 索引 | 未开始 | 本地已验证 `codegraph index` 可用 | 编写流水线脚本 |
| 6 | CodeGraph 索引上传 OSS | 未开始 | OSS 目录结构已规划 | 确认 bucket、AK/SK、生命周期 |
| 7 | Adapter 记录索引版本 | 未开始 | 表结构已规划 | 回调入库 |
| 8 | 47 部署 CodeGraph Worker | 未开始 | 47 资源检查通过，Node/npm 已安装 | 安装 CodeGraph，新增 Worker 服务 |
| 9 | Worker 下载/校验/解压/缓存/查询 | 未开始 | Worker 职责已定义 | 实现最小 `impact` 查询 |
| 10 | workflow 保存 `knowledgeContext` | 未开始 | `WorkflowRequirementRequest.extra` 可承载 | 扩展状态和上下文字段写入 |
| 11 | Codex 生成需求模板和 coding spec | 未开始 | 方案已定义 skill 方向 | 先沉淀模板和 prompt/skill |

一期完成标准：

```text
一个真实需求可以读取需求文档。
能识别 projectKey。
能查询知识图谱。
能取得指定 commit 的 CodeGraph 影响面。
能把 knowledgeContext 写入 workflow。
能生成需求模板和 coding spec。
```

## 3. 二期进度

二期目标：

```text
打通代码提交后的交付闭环。
```

| 序号 | 事项 | 状态 | 当前证据 | 下一步 |
| --- | --- | --- | --- | --- |
| 1 | 提交信息带 `workflowId` / 任务号 / 版本号 | 未开始 | 已有提交说明模板 | 扩展提交模板和校验规则 |
| 2 | 合并 develop 后触发 CI/CD | 部分完成 | 云效流水线已可回调 Adapter | 绑定 workflowId / commitId |
| 3 | CI 成功推进 workflow | 部分完成 | 已有流水线成功处理逻辑 | 增加 `PIPELINE_SUCCESS` 后置门禁 |
| 4 | CI 失败进入 `PIPELINE_FAILED` | 部分完成 | 已有失败分析和回调逻辑 | 绑定重试回到 `CODING_REQUESTED` |
| 5 | CI 后生成新 CodeGraph 索引 | 未开始 | 方案已定义 | 接入流水线索引脚本 |
| 6 | CodeGraph 索引回调推进 `CODEGRAPH_INDEXED` | 未开始 | 状态已定义 | 增加状态推进逻辑 |
| 7 | CI 成功后上传 Apifox | 部分完成 | 已有 Apifox 清洗/同步链路 | 绑定到正式闭环状态 |
| 8 | Apifox 成功后关单 | 部分完成 | 已有云效关单能力 | 增加 `APIFOX_SYNCED` 门禁 |
| 9 | 审计链路完整留痕 | 部分完成 | 已有 `adapter_audit` 和日志 | 覆盖 CodeGraph / knowledge 事件 |

二期完成标准：

```text
代码合并 develop 后能自动进入 CI 状态。
CI 成功后能上传 Apifox。
CodeGraph 新索引能上传 OSS 并回调 Adapter。
Apifox 成功后才能关单。
失败不会误关单，能进入 NEEDS_HUMAN 或 CODING_REQUESTED。
```

## 4. 最终形态进度

| 能力 | 当前状态 | 达成标准 |
| --- | --- | --- |
| 多项目统一接入 | 未完成 | 任意项目通过配置接入，不改主流程代码 |
| 需求到上下文 | 未完成 | 每个需求都有业务知识 + 代码影响面 |
| 上下文到 spec | 未完成 | 每个任务编码前都有 spec 和检查清单 |
| spec 到 coding | 部分依赖 Codex | Codex 根据 spec 执行，不盲改 |
| coding 到 CI | 部分完成 | 提交结果写回 workflow，CI 回调可追踪 |
| CI 到 Apifox | 部分完成 | CI 成功后同步接口资产 |
| Apifox 到关单 | 部分完成 | Apifox 成功后自动关闭任务 |
| 全链路审计 | 部分完成 | 每个关键动作写入 workflow event / audit |

## 5. 最近建议执行顺序

| 优先级 | 事项 | 原因 |
| --- | --- | --- |
| P0 | 建 `adapter_project_config` | 多项目能力的基础 |
| P0 | 建 `adapter_codegraph_index` | CodeGraph 远端索引版本的基础 |
| P0 | 新增 `/adapter/codegraph/index-callback` | 让流水线能把索引结果写回 Adapter |
| P0 | 新增 `/adapter/knowledge/query` | 让需求可以统一查询业务知识 |
| P1 | 在 47 部署轻量 CodeGraph Worker | 打通知识上下文里的代码影响面 |
| P1 | Codeup / 云效流水线上传 CodeGraph 索引到 OSS | 建立远端索引来源 |
| P1 | workflow 写入 `knowledgeContext` | 让需求模板和 spec 有上下文 |
| P2 | 固化需求模板和 spec skill | 降低每次人工整理成本 |
| P2 | 绑定 CI / Apifox / 关单门禁 | 完成闭环 |

