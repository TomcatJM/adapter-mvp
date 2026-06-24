# Adapter MVP 云效工作项创建进度

## 2026-06-18

- 已复核 `docs/主流程落地方案.md`、`docs/云效开放接口调研方案.md`、`docs/云效工作项创建任务.md`。
- 已确认当前代码中 `REQUIREMENT_PARSED` 分支仍是 P0 占位返回。
- 准备新增云效工作项创建适配器并接入 workflow/db 状态机。
- 已新增 `app/yunxiao.py`，实现云效 `CreateWorkitemV2` payload、配置校验、脱敏和 HTTP OpenAPI 签名请求层。
- 已接入 workflow/db：`REQUIREMENT_PARSED -> YUNXIAO_TASK_CREATED -> CODING_REQUESTED`，失败保持 `REQUIREMENT_PARSED`。
- 已补 `tests/test_yunxiao_workitem_create.py`，目标测试和全量测试均通过。
- 已新增 `adapter_yunxiao_account_config` 和 `adapter_yunxiao_project_config`，用于维护云效 AK 与多个业务项目映射。
- 已将云效创建配置改为 DB 优先；MySQL 已配置时必须按项目名命中映射，缺项目/账号配置会明确失败，不会静默使用默认项目。
- 已新增 `scripts/upsert_yunxiao_config.py`，用于从环境变量读取 AK 并写入账号表，同时维护项目映射；脚本不打印 AK/Secret。
- 已补 `tests/test_yunxiao_db_config.py`，并扩展 `tests/test_yunxiao_workitem_create.py` 覆盖 DB 优先、多项目映射、缺项目映射、缺账号映射。
- 已更新 `docs/云效工作项创建任务.md`、`docs/主流程落地方案.md`、`docs/接口文档.md`、`docs/当前进度说明.md`、`docs/云效开放接口调研方案.md`。
- 验证：`python3 -m unittest discover -s tests` 通过 36 条。
- 已新增 `adapter_yunxiao_project_member` 人员配置表；`WorkflowRequirementRequest` 支持 `assigneeId` / `assigneeName`；云效创建负责人解析顺序为指定负责人、项目默认人员、旧项目默认负责人兜底。
- 已扩展 `scripts/upsert_yunxiao_config.py` 支持 `--member-name`、`--member-account-id`、`--member-default` 和 `--member-only`。
- 本地验证：bundled Python 执行 `python3 -m unittest discover -s tests` 通过 43 条。

## 2026-06-22

- 已实现云效工作项关闭/回写：`APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED`，失败进入 `NEEDS_HUMAN`。
- 已扩展 `app/yunxiao.py`：新增查询工作项、追加评论、更新完成状态/关闭流转、关单回写内容构造和已关闭幂等判断。
- 已扩展 `app/workflow.py`：`advance` 支持 `APIFOX_SYNCED` 自动关单，`YUNXIAO_TASK_CLOSED` 重复调用直接跳过。
- 已扩展 `app/db.py` 和 `sql/mysql_schema.sql`：项目配置表新增 `done_status_id`、`done_status_field_id`、`done_status_names`、`comment_field_key`、`comment_format_type`、`close_transition_id`，并新增 `update_workflow_yunxiao_task_closed` / `mark_workflow_needs_human`。
- 已扩展 `scripts/upsert_yunxiao_config.py` 支持维护关单字段。
- 已新增 `tests/test_yunxiao_workitem_close.py`，覆盖正常关闭、已关闭补偿、缺 task id、缺 done status、workflow 成功推进、重复关闭跳过、失败进 `NEEDS_HUMAN`。
- 已更新 `docs/接口文档.md`、`docs/当前进度说明.md`、`docs/后续配置清单.md`、`docs/云效工作项关闭和回写任务.md`。
- 验证：`/Users/jzm/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests` 通过 51 条。
- 已将本地关单代码部署到远端 `47.116.102.238:18080`，`/health` 返回 OK。
- 远端 DB 已补齐 `adapter_yunxiao_project_config` 关单字段，并给 `校CRM` / `jdb-school-crm` 配置 `done_status_id=100014`、`done_status_field_id=status`。
- 已用 `wf-d0e962010f1445ad` 跑通 `CODING_REQUESTED -> CODE_SUBMITTED -> PIPELINE_SUCCESS -> APIFOX_SYNCED`，Apifox 导入返回 201。
- 关单调用进入 `NEEDS_HUMAN`，原因是远端当前只有 `legacy-openclaw` 账号，`auth_type=legacy_token`，旧网关对工作项详情/评论/状态接口跳转到帮助文档，不能执行关单。
- 已补代码：`legacy_token` 关单前置报出 AK 解决方案；新增 `/workflow/{workflow_id}/resolve` 用于配置修复后把 `NEEDS_HUMAN` 恢复到 `APIFOX_SYNCED` 后重试。

## 2026-06-23

- 正在处理 `adapter-mvp` 不应使用统一网关 OpenAPI 模板的问题：保留 `APIFOX_OPENAPI_URL_TEMPLATE` 给其他项目使用，新增项目级 `adapter_apifox_project_config.openapi_url` 作为单项目覆盖。
- 已补 `app/apifox.py`、`app/db.py`、`scripts/upsert_apifox_project_config.py`、`sql/mysql_schema.sql`、README 和后续配置清单；待测试、提交、部署和远端 DB 写入真实 OpenAPI URL。
- 已提交并推送 `259a39c feat: support project-specific apifox openapi urls`，部署到 `47.116.102.238:18080`。
- 已写入远端 DB：`adapter-mvp -> Apifox 8460173 -> http://47.116.102.238:18080/openapi.json`。
- 已重放 `wf-c36d66f3271e40ba` 的 SUCCESS callback，Apifox import 返回 `201`，workflow 推进到 `APIFOX_SYNCED`。
- 正在实现真实云效 Webhook 无 `WORKFLOW_ID` 时的 `pipelineId` 自动发现：新增云效 `GetPipeline` 查询、唯一匹配已有 Apifox 项目配置、自动回写 `adapter_apifox_pipeline_config`。
- 本地验证：`.venv/bin/python -m unittest discover -s tests` 通过 74 条；系统 Python 3.9 因既有测试使用 `| None` 类型语法失败，bundled Python 3.12 因缺 FastAPI 失败，项目 `.venv` 是当前有效验证环境。
- 已部署到远端 `47.116.102.238:18080`，`/health` 返回 OK。
- 已用真实 `pipelineId=4836717` 调用云效 `GetPipeline` 验证自动发现：匹配为 `jdb-school-crm`，并写回 `adapter_apifox_pipeline_config`；后续该 pipeline 不传 `PROJECT_NAME` 也能解析到 Apifox 项目 `8019331`。
- 已实现无 `WORKFLOW_ID` 时的项目级 workflow 绑定兜底：按 `pipelineId -> projectName` 解析后，仅在该项目存在唯一可接收当前流水线事件的活跃 workflow 时绑定；支持同云效 `organization_id/project_id` 的项目别名，例如 `jdb-school-crm` / `校CRM`。
- 已新增 DB 只读 helper `list_workflows_by_statuses`，在 Python 层根据 workflow context、requirement、repoUrl、云效创建结果筛选项目，避免依赖 MySQL JSON 路径差异。
- 已扩展 `tests/test_yunxiao_pipeline_workflow_binding.py` 覆盖项目级唯一绑定和多候选歧义保护。
- 本地验证：`.venv/bin/python -m unittest discover -s tests` 通过 76 条。

## 2026-06-24

- 已修复真实云效 Webhook payload 解析：代码源字段在 `sources[0].data`，提交说明可能是 URL 编码 JSON 字符串，且云效可能只传 `CI_COMMIT_TITLE`。
- 已支持从提交说明解析 `WORKFLOW_ID` / `YUNXIAO_TASK_ID` / `云效任务ID`，并在显式任务 ID 查不到 workflow 时停止后续项目兜底，避免串错需求。
- 已用 jdb-demo 跑通真实端到端闭环：钉钉文档读取、结构化需求、云效任务创建、提交并触发云效流水线、Webhook 绑定 workflow、Apifox 导入、云效任务关闭。
- 真实闭环记录：`workflowId=wf-e7569729c0c84761`，`yunxiaoTaskId=ed95e76c53c90902357808629b`，`pipelineId=4957185`，`buildNumber=25`，`commitId=74d1f2d0c992b8bedd259eeada76d833b87fb68a`，`apifoxProjectId=8483648`。
- 最终远端 workflow 状态已查询确认：`YUNXIAO_TASK_CLOSED`；事件链为 `CREATED -> DOC_READ -> REQUIREMENT_PARSED -> YUNXIAO_TASK_CREATED -> CODING_REQUESTED -> PIPELINE_SUCCESS -> APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED`。
- 本地验证：`.venv/bin/python -m unittest discover -s tests` 通过 84 条。
