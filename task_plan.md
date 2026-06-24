# Adapter MVP 云效工作项首尾闭环计划

## Goal

按既有主流程规划，实现云效工作项创建和关闭回写闭环：

```text
REQUIREMENT_PARSED -> YUNXIAO_TASK_CREATED -> CODING_REQUESTED
APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED
```

## Phases

| Phase | Status | Notes |
| --- | --- | --- |
| 1. 复核规划和当前代码 | complete | 已确认入口为 `/workflow/{workflow_id}/advance`，云效使用 HTTP/OpenAPI。 |
| 2. 实现云效创建适配器 | complete | 新增 `app/yunxiao.py`，配置缺失必须显式失败。 |
| 3. 接入 workflow/db 状态机 | complete | 成功写入 `yunxiao_task_id` 并推进到 `CODING_REQUESTED`。 |
| 4. 补单测和文档 | complete | 覆盖成功、幂等跳过、失败不推进、脱敏。 |
| 5. 验证 | complete | `python3 -m unittest discover -s tests` 通过 30 条；无真实云效 AK 时只做单元验证。 |
| 6. 云效 AK 与多项目配置表 | complete | 新增账号 AK 表和项目映射表；MySQL 已配置时强制项目映射，缺配置明确失败；本地无 DB 时保留 env 兜底。 |
| 7. 云效项目人员表与默认负责人 | complete | 新增 `adapter_yunxiao_project_member`，支持指定负责人和项目默认负责人；旧 `default_assignee` 保留为兜底。 |
| 8. 云效工作项关闭/回写 | complete | 已接入 `APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED`；评论回写、完成状态更新、已关闭补偿、失败转 `NEEDS_HUMAN` 均有单测覆盖。 |
| 9. Apifox 项目级 OpenAPI 覆盖 | complete | 保留全局 OpenAPI 模板给其他项目，新增 `adapter_apifox_project_config.openapi_url` 支持 `adapter-mvp` 等单项目例外；远端已配置 `adapter-mvp -> 8460173 -> http://47.116.102.238:18080/openapi.json` 并重放 workflow 到 `APIFOX_SYNCED`。 |
| 10. pipelineId 自动发现 Apifox 项目 | complete | 真实云效 Webhook 拿不到 `WORKFLOW_ID` 时，先用 `pipelineId` 查本地映射；未命中则查询云效 `GetPipeline`，唯一匹配已有 Apifox 项目后回写 `adapter_apifox_pipeline_config`。远端已验证 `4836717 -> jdb-school-crm` 自动发现并缓存。 |
| 11. 无 WORKFLOW_ID 的 workflow 项目级绑定 | complete | 用 `pipelineId -> projectName` 后仅在该项目唯一活跃 workflow 时绑定；多候选返回歧义，不推进、不导入。 |
| 12. 真实端到端闭环验证 | complete | `wf-e7569729c0c84761` 已跑通 `CREATED -> DOC_READ -> REQUIREMENT_PARSED -> YUNXIAO_TASK_CREATED -> CODING_REQUESTED -> PIPELINE_SUCCESS -> APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED`；本地全量测试 84 条通过。 |

## Decisions

- 主链路使用云效 HTTP/OpenAPI，不使用 CLI。
- 云效关单只允许从 `APIFOX_SYNCED` 触发，不在流水线成功时直接关闭。
- 未配置云效 AK/组织/项目/工作项字段时直接报错并记录 workflow 事件，不静默跳过。
- 云效 AK 单独放账号配置表，项目表通过 `account_name` 关联；多个业务项目按 `project_name` 独立映射云效 `organization_id` / `project_id` / 工作项类型 / 默认负责人。
- 云效负责人按项目人员表维护，解析顺序为：请求指定 `assigneeId/assigneeName` -> 项目人员表默认负责人 -> 项目表旧 `default_assignee` 兜底；指定负责人不存在时显式失败。
- 云效关单字段放在项目配置表：`done_status_id` / `done_status_field_id` / `done_status_names` / `comment_format_type` / `close_transition_id`。
- 真实联调前必须先确认目标项目的完成状态 ID 或关闭流转 ID。
- Apifox OpenAPI 来源按 payload、项目表 `openapi_url`、项目环境变量、全局环境变量、全局模板逐级解析；单项目不走统一网关时只补项目表，不改全局模板。
- Apifox 的 `pipelineId -> projectName` 可自动发现，但只允许匹配已有 `adapter_apifox_project_config.project_name`；无法唯一匹配时继续显式失败，避免推错项目。
- `pipelineId -> projectName` 只能用于项目级 workflow 兜底绑定；只有同项目唯一活跃 workflow 时才推进，多个候选时返回 `workflow match ambiguous`。
- 标准提交说明优先把 `YUNXIAO_TASK_ID=<实际云效任务ID>` 放在提交标题或正文；真实闭环已验证 `commit_message_yunxiao_task_id` 可以绑定 workflow。

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| 系统 Python 跑业务测试时缺少 pydantic | 1 | 改用 Codex bundled Python：`/Users/jzm/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。 |
| `py_compile` 试图写入 `~/Library/Caches/com.apple.python` 被沙箱拒绝 | 1 | 不再依赖该验证，改用 bundled Python 全量 unittest 实跑。 |
