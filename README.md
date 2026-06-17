# Adapter MVP

轻量级 Adapter 网关 MVP，用于受控自动化、云效回调接入、远端动作预览/执行与审计留存。

## 1. 功能说明

- 从 `config/hosts.masked.json` 加载已脱敏的主机清单。
- 提供统一 Adapter API：
  - `POST /adapter/preview`：动作预览，不执行真实远端操作。
  - `POST /adapter/execute`：动作执行，默认需要审批参数。
  - `GET /adapter/status/{task_id}`：按任务 ID 查询执行状态。
  - `GET /adapter/audit/{task_id}`：按任务 ID 查询审计记录。
  - `POST /adapter/dingtalk/read`：通过 Adapter 托管的钉钉 OpenAPI 配置读取钉钉/Alidocs 文档或表格。
  - `POST /callbacks/yunxiao/task`：云效任务回调入口。
- 默认关闭远端执行，只有 `ALLOW_REMOTE_EXEC=true` 后才允许真实执行。
- 主机元数据与密码等密钥分离存放。
- 当前已支持 `ssh.check_connectivity` 动作。
- 执行结果会写入内存状态，并可持久化到 MySQL。
- 业务接口在配置 `ADAPTER_API_TOKEN` 后必须携带 Bearer Token。
- `/adapter/execute` 必须提供 `approvalId` 或 `approved=true`。
- 审计日志双写：文件 `logs/audit.jsonl` 与 MySQL `adapter_audit`。

## 2. 安全默认值

- 导入脚本不会打印密码。
- 密码不会保存到 `config/` 目录。
- `secrets/` 已被 git 忽略。
- SSH 真实执行必须显式开启 `ALLOW_REMOTE_EXEC=true`。
- 生产动作应优先保持 preview / approval 模式。
- 文档、日志、提交记录中禁止出现 token、密码、私钥。

## 3. 本地首次启动

```powershell
cd D:\develop\user-home\workspaces\adapter-mvp
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python scripts\import_inventory.py --source D:\document\up\user-password.xls
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 18080
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

预期返回：

```json
{"status":"ok"}
```

## 4. 环境变量配置

公网或远端部署时建议配置：

```bash
ADAPTER_API_TOKEN=replace-with-random-token
ADAPTER_DB_HOST=replace-with-mysql-host
ADAPTER_DB_PORT=3306
ADAPTER_DB_NAME=adapter
ADAPTER_DB_USER=adapter_rw
ADAPTER_DB_PASSWORD=replace-with-db-password
```

调用业务接口时请求头必须包含：

```http
Authorization: Bearer replace-with-random-token
```

开启真实 SSH 执行时，在可信服务器创建 `/etc/adapter-mvp/adapter-mvp.env`，不要打印或提交密钥：

```bash
ALLOW_REMOTE_EXEC=true
HOST_HOST_47_116_102_238_PASSWORD=replace-with-secret
ADAPTER_API_TOKEN=replace-with-random-token
```

重启服务：

```bash
systemctl restart adapter-mvp
```

## 5. Adapter Preview 示例

预览 SSH 连通性检查，不执行真实远端动作：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/adapter/preview `
  -Method POST `
  -Headers @{ Authorization = "Bearer $env:ADAPTER_API_TOKEN" } `
  -ContentType 'application/json' `
  -Body '{"taskId":"demo-1","operator":"admin","system":"ssh","action":"check_connectivity","env":"dev","params":{"hostId":"host-47-116-102-238"}}'
```

## 6. Adapter Execute 示例

执行接口默认受审批保护，必须提供 `approvalId` 或 `approved=true`：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/adapter/execute `
  -Method POST `
  -Headers @{ Authorization = "Bearer $env:ADAPTER_API_TOKEN" } `
  -ContentType 'application/json' `
  -Body '{"taskId":"demo-2","operator":"admin","system":"ssh","action":"check_connectivity","env":"dev","params":{"hostId":"host-47-116-102-238","approvalId":"manual-demo-approval"}}'
```

未带审批参数时，预期返回：

```text
403 Execute requires approvalId or approved=true
```

## 7. 本地辅助脚本

```powershell
.\scripts\call_adapter.ps1 -Mode health
.\scripts\call_adapter.ps1 -Mode preview -TaskId manual-preview-1
.\scripts\call_adapter.ps1 -Mode execute -TaskId manual-exec-1 -ApprovalId manual-approval-1
.\scripts\call_adapter.ps1 -Mode status -TaskId manual-exec-1
.\scripts\call_adapter.ps1 -Mode audit -TaskId manual-exec-1
```

### 钉钉/Alidocs 文档读取

Adapter 自己调用钉钉 OpenAPI，不依赖 OpenClaw / `dws`。钉钉应用级凭据和 token 缓存单独维护，文档读取 endpoint 模板引用应用名：

```text
adapter_dingtalk_app        # 应用名称、appKey、appSecret、access_token 缓存
adapter_dingtalk_doc_config # 文档读取配置，按 config_name 引用 app_name
```

当前默认应用名标记为 `JDB小钉`。旧表 `adapter_dingtalk_app_config` 仅保留兼容和迁移，不作为新能力的主配置入口。

配置写入脚本：

```bash
DINGTALK_APP_NAME='JDB小钉' \
DINGTALK_APP_KEY='<appKey>' \
DINGTALK_APP_SECRET='<appSecret>' \
DINGTALK_OPERATOR_ID='<operatorUserId>' \
python3 scripts/upsert_dingtalk_config.py \
  --config-name default \
  --sheet-list-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets?operatorId={operatorIdEncoded}' \
  --sheet-range-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}?operatorId={operatorIdEncoded}'
```

URL 和 JSON body 模板支持占位符：

```text
{nodeId}
{sheetId}
{range}
{nodeIdEncoded}
{sheetIdEncoded}
{rangeEncoded}
{operatorId}
{operatorIdEncoded}
```

HTTP 接口：

```http
POST /adapter/dingtalk/read
Authorization: Bearer <ADAPTER_API_TOKEN>
Content-Type: application/json
```

请求体：

```json
{
  "url": "https://alidocs.dingtalk.com/i/nodes/<nodeId>",
  "configName": "default",
  "kind": "axls",
  "range": "A1:J50",
  "timeout": 60
}
```

`kind` 可传 `adoc` 或 `axls`；如果配置了 `doc_info_url_template`，Adapter 会先查元数据自动判断。`adoc` 会返回 `kind=document` 和 `document`；`axls` 会返回 `kind=sheet`、`sheets`、`sheetId`、`rangeResult`。错误信息会做基础脱敏，不要把 token、cookie、私钥或链接片段贴到聊天和日志里。

## 8. 云效回调示例

Preview 回调示例：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/callbacks/yunxiao/task `
  -Method POST `
  -Headers @{ Authorization = "Bearer $env:ADAPTER_API_TOKEN" } `
  -ContentType 'application/json' `
  -Body '{"taskId":"yx-demo-1","operator":"yunxiao","hostId":"host-47-116-102-238","execute":false}'
```

Execute 回调必须带审批参数：

```json
{
  "taskId": "yx-demo-2",
  "operator": "yunxiao",
  "hostId": "host-47-116-102-238",
  "execute": true,
  "approvalId": "manual-yx-approval-1"
}
```

云效 Preview / Audit 拆分节点脚本：

```text
scripts/yunxiao_preview_audit.sh
```

当前已验证：

```text
云效 Preview 节点 -> Adapter preview 成功
云效 Audit 节点 -> 按同一 TASK_ID 查询 PREVIEWED 审计记录成功
```


安全 Execute 脚本，必须显式提供 `YUNXIAO_APPROVAL_ID`，否则脚本会直接失败，不会调用 execute：

```text
scripts/yunxiao_execute_approved.sh
```

执行后状态查询脚本：

```text
scripts/yunxiao_status_check.sh
```

## 9. 审计日志

审计日志会以 JSONL 形式追加，不包含密码或 token：

```text
logs/audit.jsonl
```

MySQL 审计表：

```text
adapter_audit
```

按任务查询审计接口：

```http
GET /adapter/audit/{task_id}
```

## 10. 远端运维脚本

```powershell
.\scripts\remote_status.ps1
.\scripts\remote_tail_audit.ps1 -Lines 30
.\scripts\remote_restart.ps1
```

## 11. MySQL 初始化

初始化建表：

```powershell
python scripts\init_mysql_schema.py --source D:\document\up\mysql.xlsx
```

如果运行时数据库账号没有 `CREATE` 权限，请让 DBA 执行：

```text
scripts/mysql_schema.sql
```

## 12. 文档入口

主交接文档：

```text
docs/adapter-mvp-handoff.md
```

API 交接文档：

```text
docs/adapter-api.md
```



云效 execute 审批链路详细配置见主交接文档：

```text
docs/adapter-mvp-handoff.md#13-云效-execute-审批链路配置
```

推荐节点顺序：

```text
Adapter Preview -> Adapter Audit 验证 -> 人工审批节点 -> Adapter Execute -> Adapter Status 验证 -> Adapter Audit 复核
```

## 13. 建议下一步

当前 preview/audit 链路已稳定，下一步不要直接开启无审批 execute，建议先设计：

```text
云效任务 -> Adapter preview -> Audit 验证 -> 审批参数 -> Adapter execute -> 状态回查
```

重点补齐：

- execute 审批字段来源。
- execute 阻断策略。
- execute 灰度开关。
- execute 审计与状态回查。

## 14. 当前联调状态

截至 2026-06-04，云效到 Adapter 的低风险链路已完成首次闭环：

```text
云效 Preview -> Audit 验证 -> 审批变量 -> Execute -> Status 查询 -> Audit 复核
```

已验证任务：

```text
TASK_ID=yx-4957185-11
execute status=SUCCESS
action=ssh.check_connectivity
message=SSH connectivity check succeeded
```

当前只验证了低风险 SSH 连通性检查。后续扩展其它真实动作前，必须先补风险分级、审批规则、参数白名单和审计复核。

## 15. Release 总脚本与失败分析回调

为避免每个云效节点都单独增加失败处理，Release 流水线可以把 Adapter 闭环收敛为一个主 Shell 节点：

```text
人工审批节点
  -> Adapter Release Main
```

`Adapter Release Main` 内部顺序执行：

```text
Adapter Preview
  -> Adapter Audit Preview
  -> Adapter Execute
  -> Adapter Status
  -> Adapter Final Audit
```

主脚本：

```text
scripts/yunxiao_release_main.sh
```

云效节点只需要配置必要变量并执行一行脚本内容或复制脚本全文：

```bash
bash scripts/yunxiao_release_main.sh
```

如果脚本内任何阶段失败，会自动回调：

```http
POST /callbacks/yunxiao/pipeline-failure
```

回调会携带 `TASK_ID`、`pipelineId`、`buildNumber`、`stageName`、`branchName`、`commitId`、`exitCode` 和最后 200 行日志。Adapter 会写入审计事件 `pipeline_failure`，并用内置 CI/CD Agent 规则生成失败分类、证据和处理建议。

注意：该脚本包含 execute，必须放在人工审批之后运行；CI 流水线仍然只允许 preview，不允许 execute。

## 16. Release 成功后推送 Apifox

Release 全链路成功后，可以新增一个云效 Shell 节点：

```text
Apifox Import OpenAPI
```

节点位置：

```text
Adapter Final Audit 成功
  -> Apifox Import OpenAPI
  -> 云效任务回写
```

脚本：

```text
scripts/yunxiao_apifox_import.sh
```

必要变量：

```text
APIFOX_ACCESS_TOKEN
APIFOX_PROJECT_ID
OPENAPI_URL
```

`OPENAPI_URL` 必须是 OpenAPI/Swagger 的 json 或 yaml 直链，例如：

```text
https://your-domain/v3/api-docs
https://your-domain/swagger.json
```

不要填写 Swagger UI 页面地址。

可选变量：

```text
APIFOX_TARGET_ENDPOINT_FOLDER_ID
APIFOX_TARGET_SCHEMA_FOLDER_ID
APIFOX_ENDPOINT_OVERWRITE_BEHAVIOR
APIFOX_SCHEMA_OVERWRITE_BEHAVIOR
```

默认只在 `RELEASE_RESULT=SUCCESS` 时执行；失败时跳过，避免把失败版本接口推到 Apifox。

## 17. Adapter 内置 Apifox 收口

Apifox 导入现在可以收口在 Adapter 中，不需要云效单独调用 Apifox。云效只配置统一 Webhook：

```text
POST http://47.116.102.238:18080/callbacks/yunxiao/flow-event/public
```

处理规则：

```text
statusCode=FAIL/ERROR/CANCELED/UNKNOWN -> CI/CD Agent 分析失败日志
statusCode=SUCCESS/FINISH -> Adapter 判断 Apifox 项目并导入 OpenAPI
其它状态 -> 忽略
```

Adapter 选择 Apifox 项目的优先级：

1. 云效 `globalParams` 直接传 `APIFOX_PROJECT_ID` 和 `OPENAPI_URL`。
2. 云效 `globalParams` 传 `PROJECT_NAME` / `SERVICE_NAME` / `APP_NAME` / `APIFOX_PROJECT_KEY`，Adapter 用项目名查数据库 `adapter_apifox_project_config`。
3. 云效 payload 固定且不传项目时，按 `task.pipelineId` 查数据库 `adapter_apifox_pipeline_config` 得到项目名，再查 `adapter_apifox_project_config` 得到 Apifox 项目 ID。
4. 数据库未命中时，按 `task.pipelineId` 读取兜底环境变量 `APIFOX_PIPELINE_<PIPELINE_ID>_PROJECT`，例如 `APIFOX_PIPELINE_4437990_PROJECT=jdb-order`。
5. 根据 `sources[0].repo` 的仓库名生成 `<KEY>` 后读取对应环境变量。
6. 使用 `APIFOX_DEFAULT_PROJECT_ID` 与 `OPENAPI_URL`。

安全默认值：

```text
APIFOX_AUTO_IMPORT=false
```

只有 Adapter 服务环境中配置：

```text
APIFOX_AUTO_IMPORT=true
APIFOX_ACCESS_TOKEN=...
ADAPTER_DB_HOST=...
ADAPTER_DB_NAME=...
ADAPTER_DB_USER=...
ADAPTER_DB_PASSWORD=...
```

才会真实调用 Apifox。否则成功事件只会写 `apifox_import` 审计，状态为 `SKIPPED`。

### 17.1 固定网关 OpenAPI 地址模板

Adapter 已内置默认 OpenAPI 地址模板：

```text
https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs
```

云效 Webhook 只需要在 `globalParams` 中传项目名即可：

```json
{"key":"PROJECT_NAME","value":"jdb-order"}
```

或：

```json
{"key":"SERVICE_NAME","value":"jdb-order"}
```

Adapter 会自动拼出：

```text
https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
```

项目映射建议维护在 Adapter 数据库里：

```text
adapter_apifox_pipeline_config: pipeline_id -> project_name
adapter_apifox_project_config: project_name -> apifox_project_id
```

如果以后网关地址变化，可通过环境变量覆盖模板：

```text
APIFOX_OPENAPI_URL_TEMPLATE=https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs
```

## 18. 本地修改 env 后同步到云端

本地 env 文件放在：

```text
secrets/adapter-mvp.env.local
```

该目录已被 git 忽略，不会进入交付包。可参考：

```text
secrets/adapter-mvp.env.example
```

同步到远端并重启：

```powershell
python scripts\sync_remote_env.py
```

脚本会把本地文件上传为：

```text
/etc/adapter-mvp/adapter-mvp.env
```

并执行：

```text
systemctl restart adapter-mvp
curl http://127.0.0.1:18080/health
```

脚本不会打印 token。同步后再用云效 SUCCESS Webhook 测试 Apifox 导入。

## 19. Apifox 映射本地 Smoke

本地已留存一个不调用 Apifox 的映射 smoke，用于验证“云效固定 payload、无项目参数、按 pipelineId 映射项目”的场景：

```powershell
python scripts\smoke_apifox_resolution.py
```

验收输出：

```text
apifox resolution smoke OK: pipelineId=4437990 -> jdb-order -> 7049238
apifox db config smoke OK: PROJECT_NAME=jdb-order and pipelineId=4989239 -> jdb-school-gmc -> projectId=8336358
```

## 20. 当前云效 → Apifox 验收状态

截至 2026-06-06，已用云效固定格式 SUCCESS payload 复核。当时导入目标为历史 Apifox 项目 `8280604`；当前 `jdb-order` 目标以 2026-06-09 验证的 `7049238` 为准。

```text
task.pipelineId=4437990
task.buildNumber=1260
globalParams=[]
sources[0].repo=test.git
```

Adapter 解析与导入结果：

```text
taskId=yx-flow-4437990-1260
projectName=jdb-order
projectKey=JDB_ORDER
projectId=8280604
openapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
imported=true
apifoxStatusCode=200
audit=apifox_import/IMPORTED
```

2026-06-09 续接后，`jdb-order` 重新导入目标已切换为 Apifox 项目 `7049238`，并通过数据库映射验证：

```text
taskId=yx-flow-4437990-manual-1781015553
projectName=jdb-order
projectId=7049238
projectConfigSource=database
openapiUrl=http://47.116.102.238:18080/adapter/openapi/jdb-order
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
stripProjectPath=true
imported=true
apifoxStatusCode=200
endpointCreated=0
endpointUpdated=220
endpointFailed=0
schemaIgnored=251
schemaFailed=0
audit=apifox_import/IMPORTED
```

2026-06-10 发现云效流水线 `4989239` 未配置项目映射时会回落到 `projectName=default`，并尝试导入：

```text
openapiUrl=http://47.116.102.238:18080/adapter/openapi/default
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/default/v3/api-docs
apifoxStatusCode=422
errorMessage=Invalid Parameter
```

纠正：截图和云效流水线名称显示 `4989239` 实际属于 `jdb-school-gmc`，不能靠记忆或默认项目兜底。当前已将该流水线修正为动态 DB 映射：

```text
adapter_apifox_pipeline_config.pipeline_id=4989239
adapter_apifox_pipeline_config.project_name=jdb-school-gmc
adapter_apifox_project_config.project_name=jdb-school-gmc
adapter_apifox_project_config.apifox_project_id=8336358
```

同时新增导入前 OpenAPI 校验。当前上游 GMC OpenAPI 返回：

```text
https://micro-api-test.kidcastle.com.cn/gw/jdb-school-gmc/v3/api-docs
{"msg":"token失效","code":401,"data":{"tokeninc":0}}
```

因此 Adapter 会拒绝调用 Apifox，避免把错误 JSON 或空 `paths` 导入项目：

```text
taskId=yx-flow-4989239-gmc-db-smoke-1
projectName=jdb-school-gmc
projectNameSource=database_pipeline
projectId=8336358
projectConfigSource=database
openapiUrl=http://47.116.102.238:18080/adapter/openapi/jdb-school-gmc
imported=false
reason=OpenAPI preflight failed: upstream did not return an OpenAPI document: code=401 msg=token失效
```

## 21. Apifox 项目映射数据库表

为避免在云效流水线里散落项目映射，Adapter 新增两张数据库配置表：

```sql
adapter_apifox_project_config
adapter_apifox_pipeline_config
```

`adapter_apifox_project_config` 字段：

```text
project_name       项目名称，例如 jdb-order
apifox_project_id  Apifox 项目 ID，例如 7049238
remark             备注
```

`adapter_apifox_pipeline_config` 字段：

```text
pipeline_id   云效流水线 ID，例如 4989239
project_name  项目名称，例如 jdb-school-gmc
remark        备注
```

推荐维护方式：

```powershell
python scripts\upsert_apifox_project_config.py `
  --project-name jdb-order `
  --apifox-project-id 7049238 `
  --remark 订单服务接口项目-流水线重新导入目标

python scripts\upsert_apifox_pipeline_config.py `
  --pipeline-id 4989239 `
  --project-name jdb-school-gmc `
  --remark GMC Kubernetes发布流水线
```

流水线只需要传项目名：

```json
{"key":"PROJECT_NAME","value":"jdb-order"}
```

Adapter 解析优先级：

```text
1. payload.APIFOX_PROJECT_ID
2. adapter_apifox_project_config.project_name -> apifox_project_id
3. 环境变量 APIFOX_PROJECT_<KEY>_ID
4. 环境变量 APIFOX_DEFAULT_PROJECT_ID / APIFOX_PROJECT_ID
```

因此 `jdb-order` 会优先从数据库表取到 `7049238`。

若云效 payload 不传项目名，Adapter 会先按 `pipeline_id` 从 `adapter_apifox_pipeline_config` 查到项目名，再从 `adapter_apifox_project_config` 查到对应 Apifox 项目 ID。DB 未命中时不会使用默认项目 ID 硬导。

注意：数据库映射生效需要 Adapter 服务配置 `ADAPTER_DB_HOST`、`ADAPTER_DB_NAME`、`ADAPTER_DB_USER`、`ADAPTER_DB_PASSWORD`。未配置数据库时，Adapter 会继续使用环境变量映射兜底。

当前远端已配置数据库并验证：

```text
jdb-order -> 7049238
projectConfigSource=database
```

## 22. Apifox 导入路径去项目前缀

网关 OpenAPI 当前路径带服务名前缀：

```text
/jdb-order/stuStudentOrg/checkStuPhone
```

但 Apifox 中应维护为不带项目前缀的接口路径：

```text
/stuStudentOrg/checkStuPhone
```

Adapter 默认开启：

```text
APIFOX_STRIP_PROJECT_PATH=true
```

导入时不再直接把网关 OpenAPI URL 交给 Apifox，而是让 Apifox 读取 Adapter 清洗后的 OpenAPI：

```text
http://47.116.102.238:18080/adapter/openapi/jdb-order
```

该端点会：

```text
1. 拉取 upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
2. 将 paths 中的 /jdb-order/* 改写为 /*
3. 设置 servers=[{"url":"/jdb-order"}]
4. Apifox import-openapi 使用 prependBasePath=false，避免再次追加 basePath
```

验证脚本：

```powershell
python scripts\smoke_apifox_strip_project_path.py
```
