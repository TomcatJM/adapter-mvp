# Adapter MVP 云效工作项创建发现

## 2026-06-18

- 官方云效 OpenAPI 元数据确认 `CreateWorkitemV2`：
  - Product: `devops`
  - Version: `2021-06-25`
  - Path: `POST /organization/{organizationId}/workitem`
  - Required body fields: `subject`, `assignedTo`, `spaceIdentifier`, `category`, `workitemTypeIdentifier`
  - Success response includes `success` and `workitemIdentifier`
- 云效 OpenAPI 采用阿里云 OpenAPI AK 鉴权；历史脚本里的 `YUNXIAO_TOKEN` Bearer 方式不能作为新主链路依据。
- 本地 secret 文件此前已确认没有 `YUNXIAO_*` / `ALIBABA_CLOUD_*` / `ALIYUN_*` 云效创建所需配置，所以真实联调需要后续补配置。
- 云效配置已改为 DB 优先：`adapter_yunxiao_account_config` 维护 AK/Secret/Endpoint，`adapter_yunxiao_project_config` 维护多个业务项目到云效组织、项目、工作项类型和负责人的映射。
- MySQL 已配置时，云效创建必须解析出项目名并命中项目映射；缺映射会明确失败并记录 workflow 错误，不会使用默认云效项目兜底。
- 云效负责人不再只依赖项目表单个 `default_assignee` 字段；新增 `adapter_yunxiao_project_member` 维护项目成员姓名、云效账号 ID 和默认标识。创建工作项时，指定负责人必须命中人员表；未指定时优先取人员表默认人，旧 `default_assignee` 仅作为兼容兜底。

## 2026-06-22

- 云效工作项关闭/回写已按 HTTP/OpenAPI 接入，不使用 CLI。
- 关闭入口复用 `POST /workflow/{workflow_id}/advance`，仅允许从 `APIFOX_SYNCED` 推进到 `YUNXIAO_TASK_CLOSED`。
- 关闭顺序为 `GetWorkItemInfo -> CreateWorkitemComment -> UpdateWorkitemField/UpdateWorkItem -> GetWorkItemInfo`。
- 关单配置已放入 `adapter_yunxiao_project_config`，关键字段为 `done_status_id`、`done_status_field_id`、`done_status_names`、`comment_format_type`、`close_transition_id`。
- 如果云效侧已经是完成状态，Adapter 会记录 `yunxiao_workitem_close_skipped` 并补偿推进 workflow，不重复写评论和改状态。
- 关闭失败会进入 `NEEDS_HUMAN` 并记录 `yunxiao_workitem_close_failed`，避免误报成功。
- 远端真实联调确认：`legacy_token` 兼容链路可以创建工作项，但不能用于关单。旧 endpoint `openapi-rdc.aliyuncs.com` 对 `/organization/{org}/workitems/{id}` 这类工作项详情/评论/状态接口返回跳转到帮助文档，不是业务 API。
- 云效关单真实闭环必须补 `auth_type=acs_ak` 的账号配置，并把相关项目映射切到该账号；当前缺口不是 `done_status_id`，`100014` 已配置。
- 失败后 workflow 会进入 `NEEDS_HUMAN`；需要 `/workflow/{workflow_id}/resolve` 恢复到 `APIFOX_SYNCED` 后才能重试关单。

## 2026-06-23

- 真实云效 Webhook 可以只带 `pipelineId`、`buildNumber`、`statusCode`、阶段/任务名；`WORKFLOW_ID` 在云效 Webhook 中不一定能拿到。
- Apifox 项目解析可以不依赖 `WORKFLOW_ID`：先按 `adapter_apifox_pipeline_config.pipeline_id` 查缓存，未命中时调用云效 `GetPipeline`，再用流水线名称/代码源文本唯一匹配已有 `adapter_apifox_project_config.project_name`。
- 自动发现只做“唯一匹配已有项目配置”；不做默认项目兜底，不做模糊猜测，避免统一 Webhook 推错 Apifox 项目。
- `pipelineId` 解析出的项目名不足以唯一代表 workflow；安全绑定规则必须是先尝试 `WORKFLOW_ID`、云效工作项 ID、`pipelineId + buildNumber`、`branchName + commitId`，最后才按项目唯一活跃 workflow 兜底。
- 项目兜底绑定必须允许同一云效 `organization_id/project_id` 下的别名，例如代码项目 `jdb-school-crm` 和中文项目 `校CRM`，否则真实 workflow 可能因云效创建结果存中文项目名而无法绑定。
- 如果同项目有多个活跃 workflow，正确行为是返回 `workflow match ambiguous`，不推进 workflow，也不触发 Apifox 导入。

## 2026-06-24

- 真实云效 Webhook 的代码源信息会放在 `sources[0].data`，不能只读 `sources[0]`。
- 云效提交说明字段可能是 URL 编码的 JSON 字符串，也可能只出现在 `CI_COMMIT_TITLE`；Adapter 必须统一解码后再解析任务编号。
- 提交说明中放 `YUNXIAO_TASK_ID=<页面展示ID>` 可以稳定绑定 workflow，真实绑定来源为 `commit_message_yunxiao_task_id`；内部 `workitemIdentifier` 仍兼容。
- 标准提交标题推荐：`feat: <说明> YUNXIAO_TASK_ID=VEGZ-1186`；如果标题放不下，可在正文单独一行写 `云效任务ID：VEGZ-1186`。
- 最新真实闭环 `wf-e7569729c0c84761` 已最终进入 `YUNXIAO_TASK_CLOSED`，说明从钉钉需求到云效关单这条主线已经闭环。
