# Adapter MVP 交付与接口留存文档

> 本文档是 Adapter MVP 的主交付文档。后续新增接口、回调、调用脚本、curl/PowerShell 示例、部署命令、验证命令都必须同步维护到本文档或本文档链接的子文档中。禁止写入 token、密码、私钥等密钥。

## 1. 当前部署信息

| 项 | 值 |
| --- | --- |
| 公网地址 | `http://47.116.102.238:18080` |
| 远端服务器 | `47.116.102.238` |
| 登录账号 | `root` |
| 应用目录 | `/opt/adapter-mvp` |
| systemd 服务 | `adapter-mvp` |
| systemd 文件 | `/etc/systemd/system/adapter-mvp.service` |
| 环境变量文件 | `/etc/adapter-mvp/adapter-mvp.env` |
| 审计日志文件 | `/opt/adapter-mvp/logs/audit.jsonl` |
| logrotate 文件 | `/etc/logrotate.d/adapter-mvp` |
| 本地项目目录 | `D:\develop\user-home\workspaces\adapter-mvp` |

`/etc/adapter-mvp/adapter-mvp.env` 包含密码和 API token，不要复制到聊天、工单、日志或代码仓库。

## 2. 安全规则

1. `/health` 不需要 token，用于探活。
2. 业务接口必须带：

   ```http
   Authorization: Bearer <ADAPTER_API_TOKEN>
   ```

3. `/adapter/execute` 和云效回调 execute 必须带：
   - `approvalId`
   - 或 `approved=true`
4. 密码只允许放在：
   - 远端 `/etc/adapter-mvp/adapter-mvp.env`
   - 本地被 `.gitignore` 忽略的 `secrets/`
5. 审计日志和数据库不得记录密码/token。

## 3. 环境变量

远端环境变量文件：

```text
/etc/adapter-mvp/adapter-mvp.env
```

当前支持：

```bash
ALLOW_REMOTE_EXEC=true
HOST_HOST_47_116_102_238_PASSWORD=<masked>
ADAPTER_API_TOKEN=<masked>
ADAPTER_DB_HOST=<masked>
ADAPTER_DB_PORT=3306
ADAPTER_DB_NAME=adapter
ADAPTER_DB_USER=adapter_rw
ADAPTER_DB_PASSWORD=<masked>
```

## 4. API 列表

### 4.1 Health

```http
GET /health
```

示例：

```bash
curl -sS http://47.116.102.238:18080/health
```

响应：

```json
{"status":"ok"}
```

### 4.2 Adapter Preview

```http
POST /adapter/preview
```

请求头：

```http
Authorization: Bearer <ADAPTER_API_TOKEN>
Content-Type: application/json
```

请求体：

```json
{
  "taskId": "preview-demo-1",
  "operator": "admin",
  "system": "ssh",
  "action": "check_connectivity",
  "env": "dev",
  "params": {
    "hostId": "host-47-116-102-238"
  }
}
```

响应示例：

```json
{
  "task_id": "preview-demo-1",
  "system": "ssh",
  "action": "check_connectivity",
  "env": "dev",
  "risk": "low",
  "need_approval": false,
  "blocked": false
}
```

### 4.3 Adapter Execute

```http
POST /adapter/execute
```

请求体必须包含审批：

```json
{
  "taskId": "execute-demo-1",
  "operator": "admin",
  "system": "ssh",
  "action": "check_connectivity",
  "env": "dev",
  "params": {
    "hostId": "host-47-116-102-238",
    "approvalId": "manual-approval-1"
  }
}
```

成功响应：

```json
{
  "task_id": "execute-demo-1",
  "status": "SUCCESS",
  "message": "SSH connectivity check succeeded"
}
```

无审批响应：

```text
403 Execute requires approvalId or approved=true
```

### 4.4 Adapter Status

```http
GET /adapter/status/{task_id}
```

示例：

```bash
curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  http://47.116.102.238:18080/adapter/status/execute-demo-1
```

说明：

- 优先查内存。
- 服务重启后可从 MySQL `adapter_status` 恢复。

### 4.5 Adapter Audit

```http
GET /adapter/audit/{task_id}
```

示例：

```bash
curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  http://47.116.102.238:18080/adapter/audit/preview-demo-1
```

响应示例：

```json
{
  "taskId": "preview-demo-1",
  "items": [
    {
      "event": "preview",
      "taskId": "preview-demo-1",
      "operator": "admin",
      "status": "PREVIEWED"
    }
  ]
}
```

### 4.6 Yunxiao Callback

```http
POST /callbacks/yunxiao/task
```

#### Preview 请求

```json
{
  "taskId": "yx-preview-1",
  "operator": "yunxiao",
  "hostId": "host-47-116-102-238",
  "execute": false
}
```

#### Execute 请求

```json
{
  "taskId": "yx-execute-1",
  "operator": "yunxiao",
  "hostId": "host-47-116-102-238",
  "execute": true,
  "approvalId": "yx-approval-1"
}
```

### 4.7 DingTalk / Alidocs Read

```http
POST /adapter/dingtalk/read
Authorization: Bearer <ADAPTER_API_TOKEN>
Content-Type: application/json
```

用途：Adapter 使用数据库中的钉钉应用凭据和文档 API endpoint 模板，优先读取 `alidocs.dingtalk.com/i/nodes/<nodeId>` 文档或表格，供 Codex 后续查看钉钉文档时自动调用。如果 Adapter 不可用或读取失败，Codex 可以降级到 OpenClaw / `dws`，但必须明确提示当前使用 `OpenClaw fallback`。不要改成浏览器抓取。

配置表：

```text
adapter_dingtalk_app        # 应用名称、appKey、appSecret、access_token 缓存
adapter_dingtalk_doc_config # 文档读取配置，按 config_name 引用 app_name
```

当前默认应用名是 `JDB小钉`。旧表 `adapter_dingtalk_app_config` 只保留兼容。

写入配置：

```bash
DINGTALK_APP_KEY='<appKey>' \
DINGTALK_APP_SECRET='<appSecret>' \
DINGTALK_OPERATOR_ID='<operatorUserId>' \
python3 scripts/upsert_dingtalk_config.py --config-name default --app-name 'JDB小钉' \
  --sheet-list-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets?operatorId={operatorIdEncoded}' \
  --sheet-range-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}?operatorId={operatorIdEncoded}'
```

请求体：

```json
{
  "url": "https://alidocs.dingtalk.com/i/nodes/<nodeId>",
  "nodeId": null,
  "configName": "default",
  "kind": "axls",
  "sheetId": null,
  "range": "A1:J50",
  "timeout": 60
}
```

返回：

- `adoc`：`kind=document`，正文在 `document`。
- `axls`：`kind=sheet`，表格数据在 `rangeResult`，默认只读 `A1:J50`。

安全约束：不要把 appKey、appSecret、token、cookie、私钥、认证头、钉钉链接片段写入聊天、日志、工单或源码。

## 5. 云效 Shell 配置

云效中建议：

```text
是否指定运行Shell：是
Shell：bash
```

### 5.1 Preview 脚本

```bash
set -euo pipefail

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"

curl -sS -X POST "http://47.116.102.238:18080/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "host-47-116-102-238",
    "execute": false
  }'
```

### 5.2 Execute 脚本

先不要默认开启 execute。需要执行时必须由云效审批/人工审批节点注入 `YUNXIAO_APPROVAL_ID`，禁止使用默认审批号：

```bash
set -euo pipefail

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
: "${YUNXIAO_APPROVAL_ID:?YUNXIAO_APPROVAL_ID is required before execute}"

curl -sS -X POST "http://47.116.102.238:18080/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "host-47-116-102-238",
    "execute": true,
    "approvalId": "'"${YUNXIAO_APPROVAL_ID}"'"
  }'
```



本地已留存安全 execute 脚本，脚本会强制要求 `YUNXIAO_APPROVAL_ID`，未提供时直接失败，不会调用 execute：

```text
scripts/yunxiao_execute_approved.sh
```

执行后可用状态查询脚本检查同一 `TASK_ID`：

```text
scripts/yunxiao_status_check.sh
```

### 5.3 Preview 后同节点查询 Audit

联调阶段建议先放在同一个云效 Shell 节点中：先调用 preview，再立即调用 audit 查询同一个 `TASK_ID`，确认本次云效触发已入库。
本地已留存同等脚本，便于后续复制到云效 Shell 或同步到远端：

```text
scripts/yunxiao_preview_audit.sh
```

如果云效节点支持从仓库/制品读取脚本，也可以执行该脚本；否则直接复制下方脚本内容到云效 Shell 节点。

```bash
set -euo pipefail

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
BASE_URL="http://47.116.102.238:18080"
HOST_ID="host-47-116-102-238"

# 1. preview：只预览，不执行远端动作
curl -sS -X POST "${BASE_URL}/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "'"${HOST_ID}"'",
    "execute": false
  }'

echo ""
echo "---- audit ----"

# 2. audit：查询同一个 TASK_ID 的审计记录，验证已入库
curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/audit/${TASK_ID}"

echo ""
```

预期结果：

- preview 响应中 `mode` 为 `preview`。
- `task_id` 不再是 `manual-yx-preview`，而是类似 `yx-4957185-构建号`。
- audit 响应中能看到同一个 `taskId` 的 `preview` 记录。

稳定后再拆成两个节点：

1. Adapter Preview 节点。
2. Adapter Audit 验证节点。

## 6. 本地调用脚本

本地 token 文件：

```text
secrets/adapter_api_token.txt
```

调用：

```powershell
.\scripts\call_adapter.ps1 -Mode health
.\scripts\call_adapter.ps1 -Mode preview -TaskId local-preview-1
.\scripts\call_adapter.ps1 -Mode execute -TaskId local-exec-1 -ApprovalId local-approval-1
.\scripts\call_adapter.ps1 -Mode status -TaskId local-exec-1
.\scripts\call_adapter.ps1 -Mode audit -TaskId local-exec-1
```

## 7. 运维脚本

```powershell
.\scripts\remote_status.ps1
.\scripts\remote_tail_audit.ps1 -Lines 30
.\scripts\remote_restart.ps1
```

## 8. MySQL 持久化

数据库来源：

```text
D:\document\up\mysql.xlsx
```

表：

```text
adapter_status
adapter_audit
```

建表脚本：

```text
sql/mysql_schema.sql
```

初始化：

```powershell
python scripts\init_mysql_schema.py --source D:\document\up\mysql.xlsx
```

### 8.1 adapter_status

| 字段 | 注释 |
| --- | --- |
| task_id | 任务ID |
| status | 任务状态：SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知 |
| message | 状态说明 |
| data_json | 安全结果数据JSON |
| updated_at | 更新时间 |

### 8.2 adapter_audit

| 字段 | 注释 |
| --- | --- |
| id | 自增主键 |
| ts | 事件时间 |
| event | 事件类型：preview预览，execute执行，status状态查询 |
| task_id | 任务ID |
| operator | 操作人 |
| system_name | 适配系统 |
| action_name | 适配动作 |
| env_name | 环境 |
| host_id | 主机ID |
| approval_id | 审批ID |
| approved | 是否显式审批：1是，0否 |
| status | 执行状态：PREVIEWED已预览，BLOCKED已阻断，SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知 |
| message | 执行说明 |
| elapsed_ms | 耗时毫秒 |
| payload_json | 安全审计载荷JSON |

## 9. 审计留存

当前双写：

1. 文件：

   ```text
   /opt/adapter-mvp/logs/audit.jsonl
   ```

2. MySQL：

   ```text
   adapter_audit
   ```

查询：

```http
GET /adapter/audit/{task_id}
```

## 10. 常见问题

### 10.1 返回 401

未传 token：

```http
Authorization: Bearer <ADAPTER_API_TOKEN>
```

### 10.2 返回 403

可能原因：

- token 错误
- execute 缺少 `approvalId` 或 `approved=true`

### 10.3 taskId 是 manual-yx-preview

说明云效变量没有取到，当前使用了脚本默认值。需要确认云效真实变量名，再替换：

```bash
PIPELINE_ID
BUILD_NUMBER
BUILD_USER
```

### 10.4 服务重启

```powershell
.\scripts\remote_restart.ps1
```

### 10.5 查看远端日志

```powershell
.\scripts\remote_tail_audit.ps1 -Lines 50
```

## 11. 后续维护规则

1. 新增接口必须补本文档。
2. 新增调用脚本必须补本文档。
3. 新增数据库表/字段必须补注释和枚举说明。
4. 新增云效调用参数必须补示例请求/响应。
5. 不得在文档中出现真实 token、密码、私钥。




## 12. 联调验证记录

### 12.1 2026-06-04 云效 Preview 后同节点查询 Audit 成功

云效同一个 Shell 节点已完成 preview 调用，并立即查询同一个 `TASK_ID` 的 audit 入库记录。

验证结果：

```text
TASK_ID=yx-4957185
OPERATOR=yunxiao
preview mode=preview
audit event=preview
audit status=PREVIEWED
audit taskId=yx-4957185
audit operator=yunxiao
audit hostId=host-47-116-102-238
```

结论：

- 云效真实 `TASK_ID` 已接入 Adapter。
- `/callbacks/yunxiao/task` preview 调用成功。
- `/adapter/audit/{task_id}` 可查到同一任务的审计记录。
- 审计已落库，当前返回记录包含 id `7` 和 `6` 两条 preview 记录。
- 当前仍保持 preview 模式，未开启 execute。

### 12.2 2026-06-04 云效 Preview / Audit 拆分节点成功

云效已从“同一个 Shell 节点 preview 后立即查 audit”拆成两个节点：

1. Adapter Preview 节点。
2. Adapter Audit 验证节点。

验证结果：

```text
TASK_ID=yx-4957185-7
preview mode=preview
preview task_id=yx-4957185-7
audit taskId=yx-4957185-7
audit id=8
audit event=preview
audit operator=yunxiao
audit status=PREVIEWED
audit hostId=host-47-116-102-238
```

结论：

- 两个云效节点生成并使用了同一个 `TASK_ID`。
- Preview 节点调用 `/callbacks/yunxiao/task` 成功。
- Audit 节点调用 `/adapter/audit/{task_id}` 成功。
- MySQL 审计记录已可按任务 ID 查询到。
- 当前仍保持 preview 模式，未开启 execute。

## 13. 云效 Execute 审批链路配置

> 当前只准备配置，不建议直接在生产任务上启用。首次 execute 仅用于低风险 `ssh.check_connectivity`，且必须经过人工审批节点。

### 13.1 推荐节点顺序

```text
Adapter Preview
  -> Adapter Audit 验证
  -> 人工审批节点
  -> Adapter Execute
  -> Adapter Status 验证
  -> Adapter Audit 复核
```

### 13.2 人工审批节点

人工审批节点需要产出审批号，并传给后续 Shell 节点：

```text
YUNXIAO_APPROVAL_ID
```

审批号建议规则：

```text
yx-approval-${PIPELINE_ID}-${BUILD_NUMBER}
```

如果云效审批节点不能直接产出环境变量，可以在审批后新增一个 Shell 节点显式生成：

```bash
set -euo pipefail

export YUNXIAO_APPROVAL_ID="yx-approval-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
echo "YUNXIAO_APPROVAL_ID=${YUNXIAO_APPROVAL_ID}"
```

注意：不要把 token、密码、私钥作为审批变量输出。

### 13.3 Adapter Execute 节点

节点名称建议：

```text
Adapter Execute
```

执行脚本：

```bash
bash /opt/adapter-mvp/scripts/yunxiao_execute_approved.sh
```

或复制脚本内容到云效 Shell 节点。该脚本会强制检查：

```text
ADAPTER_API_TOKEN
YUNXIAO_APPROVAL_ID
```

如果没有 `YUNXIAO_APPROVAL_ID`，脚本会在调用 Adapter 前失败。

### 13.4 Adapter Status 验证节点

节点名称建议：

```text
Adapter Status 验证
```

执行脚本：

```bash
bash /opt/adapter-mvp/scripts/yunxiao_status_check.sh
```

预期成功响应：

```json
{
  "task_id": "yx-4957185-7",
  "status": "SUCCESS",
  "message": "SSH connectivity check succeeded"
}
```

### 13.5 Adapter Audit 复核节点

Execute 后建议再查一次 audit，确认同一个 `TASK_ID` 下同时存在 preview 和 execute 记录：

```bash
set -euo pipefail

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
BASE_URL="http://47.116.102.238:18080"

curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/audit/${TASK_ID}"

echo ""
```

预期 audit 至少包含：

```text
event=preview status=PREVIEWED
event=execute status=SUCCESS
```

### 13.6 Execute 启用前检查清单

启用 execute 前必须确认：

- Preview 节点成功。
- Audit 验证节点能查到 `PREVIEWED`。
- 人工审批节点已通过。
- 后续节点可以拿到 `YUNXIAO_APPROVAL_ID`。
- Execute 节点只针对低风险 `ssh.check_connectivity`。
- Status 节点可以查询同一个 `TASK_ID`。
- Audit 复核节点可以看到 execute 审计记录。
- 日志和文档中没有 token、密码、私钥。

### 13.7 2026-06-04 人工审批变量验证成功

云效审批后变量验证节点已输出：

```text
TASK_ID=yx-4957185-8
YUNXIAO_APPROVAL_ID=yx-approval-4957185-8
approval variable ready
```

结论：

- 审批号命名规则可用：`yx-approval-${PIPELINE_ID}-${BUILD_NUMBER}`。
- 当前流水线任务 ID 与审批号能按同一构建号生成。
- 下一步可以接 Adapter Execute 节点。

注意：Shell 节点内定义的变量默认只在当前节点进程内有效。若 Execute 是另一个节点，需要二选一：

1. 在 Execute 节点里重新按同样规则设置 `YUNXIAO_APPROVAL_ID`。
2. 使用云效流水线变量/输出变量机制，把 `YUNXIAO_APPROVAL_ID` 传给后续节点。

当前建议先采用方案 1，简单稳定：Execute 节点开头重新设置同样的 `TASK_ID` 和 `YUNXIAO_APPROVAL_ID`，再调用脚本。

### 13.8 2026-06-04 Execute 节点脚本路径问题修正

云效 Execute 节点报错：

```text
bash: /opt/adapter-mvp/scripts/yunxiao_execute_approved.sh: No such file or directory
```

原因：

- `/opt/adapter-mvp/scripts/yunxiao_execute_approved.sh` 位于 Adapter 服务器。
- 云效 Shell 节点运行在云效执行机，不是在 Adapter 服务器。
- 因此云效节点不能直接执行 Adapter 服务器本地路径。

修正方式：云效节点直接粘贴完整 Shell 内容，通过 HTTP 调用 Adapter 公网接口。

Adapter Execute 节点使用以下脚本：

```bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
OPERATOR="${BUILD_USER:-yunxiao}"
YUNXIAO_APPROVAL_ID="yx-approval-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
BASE_URL="http://47.116.102.238:18080"
HOST_ID="host-47-116-102-238"

echo "TASK_ID=${TASK_ID}"
echo "YUNXIAO_APPROVAL_ID=${YUNXIAO_APPROVAL_ID}"
echo "=== Adapter execute ==="

curl -sS -X POST "${BASE_URL}/callbacks/yunxiao/task" \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "taskId": "'"${TASK_ID}"'",
    "operator": "'"${OPERATOR}"'",
    "hostId": "'"${HOST_ID}"'",
    "execute": true,
    "approvalId": "'"${YUNXIAO_APPROVAL_ID}"'"
  }'

echo ""
```

Adapter Status 节点也不要执行 `/opt/...` 本地路径，直接使用 HTTP：

```bash
set -euo pipefail

: "${ADAPTER_API_TOKEN:?ADAPTER_API_TOKEN is required}"

TASK_ID="yx-${PIPELINE_ID:-manual}-${BUILD_NUMBER:-0}"
BASE_URL="http://47.116.102.238:18080"

echo "TASK_ID=${TASK_ID}"
echo "=== Adapter status ==="

curl -sS \
  -H "Authorization: Bearer ${ADAPTER_API_TOKEN}" \
  "${BASE_URL}/adapter/status/${TASK_ID}"

echo ""
```

文档保留 `/opt/adapter-mvp/scripts/*.sh` 作为 Adapter 服务器侧留存脚本，但云效节点应复制脚本内容或使用 HTTP 调用，不应直接执行 `/opt/...` 路径。

### 13.9 2026-06-04 云效 Execute 首次联调成功

云效 Execute 节点已使用 inline HTTP 脚本调用 Adapter 成功，任务：

```text
TASK_ID=yx-4957185-11
YUNXIAO_APPROVAL_ID=yx-approval-4957185-11
```

Execute 返回：

```text
source=yunxiao
mode=execute
task_id=yx-4957185-11
status=SUCCESS
message=SSH connectivity check succeeded
hostId=host-47-116-102-238
platform=腾讯
ip=47.116.102.238
account=root
elapsedMs=135
```

Adapter 接口复核结果：

```text
GET /adapter/status/yx-4957185-11 -> SUCCESS
GET /adapter/audit/yx-4957185-11 -> preview + execute + status 三类记录均存在
```

审计记录：

```text
id=12 event=preview status=PREVIEWED operator=yunxiao
id=13 event=execute status=SUCCESS operator=yunxiao approvalId=yx-approval-4957185-11 elapsedMs=135
id=14 event=status status=SUCCESS message=SSH connectivity check succeeded
```

结论：

- 云效 Preview 已通。
- 云效 Audit 验证已通。
- 人工审批变量已通。
- 云效 Execute 已通。
- Adapter Status 查询已通。
- Adapter Audit 复核已通。
- 当前执行动作仅为低风险 `ssh.check_connectivity`。
- 未发现 token、密码、私钥输出。

## 14. Release 总脚本与流水线失败分析回调

### 14.1 目标

用户反馈“每个节点都加失败回调太麻烦”。因此 Release 不再要求 Preview / Audit / Execute / Status / Final Audit 分散到多个 Shell 节点，而是收敛到一个总脚本：

```text
scripts/yunxiao_release_main.sh
```

### 14.2 云效节点放置位置

推荐流水线结构：

```text
Release 参数校验
  -> 编译/测试/质量检查
  -> 人工审批
  -> Adapter Release Main
  -> 云效任务回写
```

`Adapter Release Main` 必须放在人工审批之后，因为它内部会执行 Adapter execute。

### 14.3 总脚本内部阶段

```text
Adapter Preview
  -> Adapter Audit Preview
  -> Adapter Execute
  -> Adapter Status
  -> Adapter Final Audit
```

脚本顶部只有一个 `trap on_error ERR`，内部任一阶段失败都会进入同一个失败处理函数。

### 14.4 失败回调接口

新增接口：

```http
POST /callbacks/yunxiao/pipeline-failure
```

请求字段：

| 字段 | 说明 |
| --- | --- |
| taskId | 本次 Release 主链路 ID，例如 `rel-${REQUIREMENT_ID}-${BUILD_NUMBER}` |
| pipelineId | 云效流水线 ID |
| buildNumber | 云效构建号 |
| stageName | 总脚本内失败阶段 |
| branchName | 分支名 |
| commitId | 提交 ID |
| operator | 触发人 |
| exitCode | 失败退出码 |
| logTail | 最后 200 行日志 |

Adapter 会记录审计事件：

```text
pipeline_failure
```

并返回 CI/CD Agent 分析结果：

```json
{
  "category": "compile_error | test_failure | dependency_error | adapter_execute_failed | quality_gate_failed | unknown",
  "confidence": "high | medium | low",
  "summary": "失败摘要",
  "evidence": ["命中的日志特征"],
  "suggestion": ["处理建议"],
  "shouldBlockRelease": true
}
```

### 14.5 最小落地方式

云效只需要一个 Shell 节点复制 `scripts/yunxiao_release_main.sh` 内容，或先把脚本放到可访问仓库后执行：

```bash
bash scripts/yunxiao_release_main.sh
```

必要变量：

```text
ADAPTER_API_TOKEN
REQUIREMENT_ID
PIPELINE_ID
BUILD_NUMBER
BUILD_USER
BRANCH_NAME
COMMIT_ID
```

可选变量：

```text
ADAPTER_BASE_URL
ADAPTER_HOST_ID
YUNXIAO_APPROVAL_ID
WORKSPACE
```

### 14.6 边界

- 这个总脚本只解决 Adapter Release 闭环失败分析。
- 编译/测试如果仍然在独立云效节点里，失败不会进入该脚本；要么把编译/测试也收敛进一个 CI 总脚本，要么在云效使用“失败后执行/always run”收口节点。
- CI 流水线不能复用该脚本，因为该脚本包含 execute。

## 15. Release 成功后对接 Apifox

### 15.1 节点顺序

```text
Release 成功
  -> Adapter Final Audit 复核通过
  -> Apifox Import OpenAPI
  -> 云效任务回写
```

### 15.2 调用方式

使用 Apifox 开放 API 导入 OpenAPI/Swagger：

```text
POST https://api.apifox.com/v1/projects/{projectId}/import-openapi?locale=zh-CN
```

Header：

```text
X-Apifox-Api-Version: 2024-03-28
Authorization: Bearer ${APIFOX_ACCESS_TOKEN}
Content-Type: application/json
```

Body 核心字段：

```json
{
  "input": {
    "url": "${OPENAPI_URL}"
  },
  "options": {
    "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
    "schemaOverwriteBehavior": "KEEP_EXISTING",
    "updateFolderOfChangedEndpoint": true,
    "prependBasePath": true
  }
}
```

### 15.3 云效脚本

已新增：

```text
scripts/yunxiao_apifox_import.sh
```

必要变量：

```text
APIFOX_ACCESS_TOKEN
APIFOX_PROJECT_ID
OPENAPI_URL
```

注意：`OPENAPI_URL` 必须是 JSON/YAML 直链，不是 Swagger UI 页面。

### 15.4 验收

Apifox 返回 `endpointCreated/endpointUpdated/endpointFailed` 等 counters。验收条件：

```text
endpointFailed = 0
schemaFailed = 0
```

如果导入失败，不推进云效任务“接口文档已同步”。

## 16. Adapter 内置 Apifox 收口

### 16.1 目标

Apifox 导入不放在云效 Shell 节点里，统一收口到 Adapter：

```text
云效 Webhook
  -> Adapter /callbacks/yunxiao/flow-event/public
  -> Adapter 根据 statusCode 判断
  -> 成功时选择 Apifox 项目并导入 OpenAPI
```

### 16.2 状态判断

```text
FAIL / FAILED / ERROR / CANCELED / UNKNOWN / UNKOWN
  -> pipeline_failure 审计 + CI/CD Agent 分析

SUCCESS / FINISH
  -> apifox_import 审计 + Apifox 导入判断

RUNNING / WAITING / SKIP
  -> ignored
```

### 16.3 项目选择规则

优先级从高到低：

1. `globalParams` 直接传：

```text
APIFOX_PROJECT_ID
OPENAPI_URL
```

2. 按云效流水线 ID 查询数据库映射项目（当前推荐）：

云效 Webhook 入参固定为 `task` / `sources` / `globalParams`，不从 URL query/path 传项目参数时，Adapter 可按 `task.pipelineId` 映射项目：

```text
adapter_apifox_pipeline_config.pipeline_id -> project_name
adapter_apifox_project_config.project_name -> apifox_project_id
```

当前已验证：

```text
adapter_apifox_pipeline_config: 4437990 -> jdb-order
adapter_apifox_pipeline_config: 4989239 -> jdb-school-gmc
adapter_apifox_project_config: jdb-order -> 7049238
adapter_apifox_project_config: jdb-school-gmc -> 8336358
APIFOX_OPENAPI_URL_TEMPLATE=https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs
```

云效 payload 即使 `globalParams` 不传项目，也会解析为：

```text
projectName=jdb-order
projectKey=JDB_ORDER
projectId=7049238
openapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
```

3. `globalParams` 传项目 key：

```text
APIFOX_PROJECT_KEY 或 SERVICE_NAME 或 APP_NAME
```

Adapter 根据 key 读取环境变量：

```text
APIFOX_PROJECT_<KEY>_ID
OPENAPI_<KEY>_URL
```

4. 如果没有 key，Adapter 从 `sources[0].repo` 提取仓库名并转成 key。

5. `OPENAPI_URL` 可作为 OpenAPI 地址兜底，但 Apifox 项目 ID 不再使用默认兜底。

```text
OPENAPI_URL
```

如果无法解析项目名或 Apifox 项目 ID，Adapter 会停止导入并返回缺少项目映射的原因，不会静默推送到默认项目。

### 16.4 安全开关

默认不真实导入：

```text
APIFOX_AUTO_IMPORT=false
```

真实导入必须在 Adapter 服务环境中配置：

```text
APIFOX_AUTO_IMPORT=true
APIFOX_ACCESS_TOKEN=...
APIFOX_PROJECT_<KEY>_ID=...
OPENAPI_<KEY>_URL=...
```

这样云效 Webhook 不需要携带 Apifox token。

### 16.5 审计

成功事件会写：

```text
event=apifox_import
status=SKIPPED 或 IMPORTED
```

失败事件仍写：

```text
event=pipeline_failure
status=ANALYSIS_READY
```

### 16.6 固定网关 OpenAPI 地址模板

用户确认 OpenAPI 地址格式：

```text
https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
```

其中 `jdb-order` 是项目名。因此 Adapter 默认模板固定为：

```text
https://micro-api-test.kidcastle.com.cn/gw/{project}/v3/api-docs
```

云效 Webhook 只需要传：

```json
{"key":"PROJECT_NAME","value":"jdb-order"}
```

或：

```json
{"key":"SERVICE_NAME","value":"jdb-order"}
```

Adapter 自动生成：

```text
OPENAPI_URL=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
PROJECT_KEY=JDB_ORDER
```

Apifox 项目映射使用 Adapter 数据库维护：

```text
adapter_apifox_pipeline_config: pipeline_id -> project_name
adapter_apifox_project_config: project_name -> apifox_project_id
```

真实导入还需要：

```text
APIFOX_AUTO_IMPORT=true
APIFOX_ACCESS_TOKEN=...
```

## 17. 本地 env 同步到云端

为了本地修改 Apifox token 后上传云端，新增：

```text
scripts/sync_remote_env.py
```

本地配置文件：

```text
secrets/adapter-mvp.env.local
```

参考模板：

```text
secrets/adapter-mvp.env.example
```

执行：

```powershell
python scripts\sync_remote_env.py
```

效果：

```text
1. 上传到 /etc/adapter-mvp/adapter-mvp.env
2. chmod 600
3. systemctl restart adapter-mvp
4. health check
```

注意：`secrets/` 被 `.gitignore` 忽略，token 不会进入代码包；脚本输出也会屏蔽 TOKEN/PASSWORD/SECRET/KEY。

## 18. Apifox 映射本地 Smoke

新增本地 smoke 脚本，不调用 Apifox，只验证云效固定 payload 下的项目解析：

```powershell
python scripts\smoke_apifox_resolution.py
```

覆盖场景：

```text
task.pipelineId=4437990
globalParams=[]
sources[0].repo=test.git
APIFOX_PIPELINE_4437990_PROJECT=jdb-order
```

验收输出：

```text
apifox resolution smoke OK: pipelineId=4437990 -> jdb-order -> 7049238
apifox db config smoke OK: PROJECT_NAME=jdb-order and pipelineId=4989239 -> jdb-school-gmc -> projectId=8336358
```

## 19. 2026-06-06 云效固定 payload 到 Apifox 导入复核

本轮继续集成时，使用云效固定格式 SUCCESS payload 复核，不通过 URL query/path 传项目参数。当时导入目标为历史 Apifox 项目 `8280604`；当前 `jdb-order` 目标以 2026-06-09 验证的 `7049238` 为准。

```text
task.pipelineId=4437990
task.buildNumber=1260
globalParams=[]
sources[0].repo=test.git
```

Adapter 返回：

```text
taskId=yx-flow-4437990-1260
pipelineId=4437990
buildNumber=1260
projectName=jdb-order
projectKey=JDB_ORDER
projectId=8280604
openapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
imported=true
reason=Apifox import finished
apifoxStatusCode=200
```

审计复核：

```text
taskId=yx-flow-4437990-1260
event=apifox_import
status=IMPORTED
message=Apifox import finished
operator=yunxiao
```

结论：当前链路已固化为 `云效 SUCCESS Webhook -> Adapter pipelineId 映射项目 -> OpenAPI 模板生成 -> Apifox import-openapi -> adapter_audit 留痕`。

## 20. Apifox 项目映射改为数据库维护

用户确认后续希望把“流水线 ID -> 项目名称 -> Apifox 项目 ID”的配置维护在数据库中，而不是散落在云效流水线或环境变量里。

### 20.1 新增表

```sql
CREATE TABLE IF NOT EXISTS adapter_apifox_project_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
    apifox_project_id VARCHAR(64) NOT NULL COMMENT 'Apifox项目ID',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_apifox_project_name (project_name),
    KEY idx_adapter_apifox_project_id (apifox_project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox项目映射配置表';

CREATE TABLE IF NOT EXISTS adapter_apifox_pipeline_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    pipeline_id VARCHAR(64) NOT NULL COMMENT '云效流水线ID',
    project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_apifox_pipeline_id (pipeline_id),
    KEY idx_adapter_apifox_pipeline_project_name (project_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox流水线项目映射配置表';
```

### 20.2 解析优先级

Adapter 当前项目 ID 解析顺序：

```text
1. 云效 payload 直接传 APIFOX_PROJECT_ID
2. 数据库 adapter_apifox_pipeline_config：pipeline_id -> project_name
3. 数据库 adapter_apifox_project_config：project_name -> apifox_project_id
4. 环境变量 APIFOX_PIPELINE_<PIPELINE_ID>_PROJECT
5. 环境变量 APIFOX_PROJECT_<KEY>_ID
```

注意：统一 Webhook URL 被多个项目共用时，不能靠默认项目 ID 判断项目。若 payload 未传项目名且 DB 中没有 `pipeline_id` 映射，Adapter 会停止导入并返回缺少项目映射。

因此流水线只需要传：

```json
{"key":"PROJECT_NAME","value":"jdb-order"}
```

Adapter 会查：

```text
adapter_apifox_project_config.project_name = jdb-order
```

并取：

```text
apifox_project_id = 7049238
```

### 20.3 维护脚本

新增：

```text
scripts/upsert_apifox_project_config.py
```

示例：

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

脚本读取数据库环境变量，不打印密码或 token。

### 20.4 2026-06-06 远端数据库配置验证（历史目标）

已使用 `D:\document\up\mysql.xlsx` 初始化 MySQL schema，并写入历史目标配置：

```text
project_name=jdb-order
apifox_project_id=8280604
remark=订单服务接口项目
```

随后已将 `ADAPTER_DB_HOST`、`ADAPTER_DB_PORT`、`ADAPTER_DB_NAME`、`ADAPTER_DB_USER`、`ADAPTER_DB_PASSWORD` 同步到远端 `/etc/adapter-mvp/adapter-mvp.env` 并重启服务。验证：

```text
process DB keys: 5
taskId=yx-flow-4437990-1263
projectName=jdb-order
projectId=8280604
projectConfigSource=database
projectRemark=订单服务接口项目
imported=true
apifoxStatusCode=200
```

结论：云效后续只需在 webhook `globalParams` 传 `PROJECT_NAME=jdb-order`，Adapter 会优先从数据库表 `adapter_apifox_project_config` 获取 Apifox 项目 ID。

### 20.5 2026-06-09 续接验证

续接时发现远端环境变量兜底已切到 `7049238`，但数据库表中 `jdb-order` 映射缺失。已重新写入数据库映射：

```text
project_name=jdb-order
apifox_project_id=7049238
remark=订单服务接口项目-流水线重新导入目标
```

历史远端配置复核：

```text
APIFOX_AUTO_IMPORT=true
APIFOX_PROJECT_JDB_ORDER_ID=7049238
APIFOX_PIPELINE_4437990_PROJECT=jdb-order
APIFOX_STRIP_PROJECT_PATH=true
ADAPTER_PUBLIC_BASE_URL=http://47.116.102.238:18080
```

当前规则已废弃 `APIFOX_DEFAULT_PROJECT_ID` 作为项目 ID 兜底；应删除该配置，并用数据库映射、`APIFOX_PROJECT_<KEY>_ID` 或 payload `APIFOX_PROJECT_ID` 显式指定目标项目。

使用运行中的 Adapter HTTP 服务触发云效 SUCCESS 事件后，真实导入结果：

```text
taskId=yx-flow-4437990-manual-1781015553
projectName=jdb-order
projectId=7049238
projectConfigSource=database
openapiUrl=http://47.116.102.238:18080/adapter/openapi/jdb-order
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
stripProjectPath=true
imported=true
reason=Apifox import finished
apifoxStatusCode=200
endpointCreated=0
endpointUpdated=220
endpointFailed=0
schemaIgnored=251
schemaFailed=0
audit=apifox_import/IMPORTED
```

### 20.6 2026-06-10 4989239 流水线映射修复

云效流水线 `4989239` 连续返回：

```text
taskId=yx-flow-4989239-30
taskId=yx-flow-4989239-31
projectName=default
projectKey=DEFAULT
projectConfigSource=unresolved
openapiUrl=http://47.116.102.238:18080/adapter/openapi/default
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/default/v3/api-docs
apifoxStatusCode=422
errorMessage=Invalid Parameter
```

原因：当时 Adapter 只支持从环境变量解析 `pipelineId -> projectName`，远端 `/etc/adapter-mvp/adapter-mvp.env` 只有 `APIFOX_PIPELINE_4437990_PROJECT=jdb-order`，缺少 `4989239` 的映射，Adapter 因此回落到 `default`。

后续曾误将 `4989239` 补为 `jdb-order`。根据云效页面当前流水线名称，`4989239` 实际属于 `jdb-school-gmc`。当前修复为：

```text
adapter_apifox_pipeline_config.pipeline_id=4989239
adapter_apifox_pipeline_config.project_name=jdb-school-gmc
adapter_apifox_project_config.project_name=jdb-school-gmc
adapter_apifox_project_config.apifox_project_id=8336358
```

GMC 上游 OpenAPI 当前返回网关业务错误，不是 OpenAPI：

```text
https://micro-api-test.kidcastle.com.cn/gw/jdb-school-gmc/v3/api-docs
{"msg":"token失效","code":401,"data":{"tokeninc":0}}
```

因此 Adapter 新增 OpenAPI 预检：上游不是 OpenAPI 或 `paths` 为空时不调用 Apifox，避免导入错误 JSON 或空接口：

```text
taskId=yx-flow-4989239-gmc-db-smoke-1
projectName=jdb-school-gmc
projectNameSource=database_pipeline
projectNameRemark=gmc-kubernetes-release-pipeline
projectId=8336358
projectConfigSource=database
projectRemark=school-gmc-api-project
openapiUrl=http://47.116.102.238:18080/adapter/openapi/jdb-school-gmc
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-school-gmc/v3/api-docs
imported=false
reason=OpenAPI preflight failed: upstream did not return an OpenAPI document: code=401 msg=token失效
```

## 21. Apifox 导入路径去项目路径前缀

用户纠正：同步到 Apifox 的接口不应带服务项目路径。正确路径应为：

```text
/stuStudentOrg/checkStuPhone
```

而不是：

```text
/jdb-order/stuStudentOrg/checkStuPhone
```

### 21.1 实现方式

Adapter 新增公开 OpenAPI 清洗端点：

```text
GET /adapter/openapi/{project_name}
```

例如：

```text
http://47.116.102.238:18080/adapter/openapi/jdb-order
```

处理逻辑：

```text
1. 拉取原始网关 OpenAPI：
   https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
2. 将 paths 中的 /jdb-order/* 改写为 /*
3. 设置 servers=[{"url":"/jdb-order"}]
4. Apifox import-openapi 使用清洗后的 Adapter URL
5. import options.prependBasePath=false，避免 Apifox 再追加 basePath
```

### 21.2 配置

默认开启：

```text
APIFOX_STRIP_PROJECT_PATH=true
ADAPTER_PUBLIC_BASE_URL=http://47.116.102.238:18080
```

Adapter 返回中会同时保留：

```text
openapiUrl=http://47.116.102.238:18080/adapter/openapi/jdb-order
upstreamOpenapiUrl=https://micro-api-test.kidcastle.com.cn/gw/jdb-order/v3/api-docs
stripProjectPath=true
```

### 21.3 验证

新增 smoke：

```powershell
python scripts\smoke_apifox_strip_project_path.py
```

预期：

```text
apifox strip project path smoke OK: /jdb-order/* -> /*
```

2026-06-09 远端清洗端点复核：

```text
path_count=196
has_unprefixed=True
has_prefixed=False
/stuStudentOrg/checkStuPhone 存在
/jdb-order/stuStudentOrg/checkStuPhone 不存在
```
