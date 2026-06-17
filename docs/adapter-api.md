# Adapter MVP API

## Base URL

```text
http://47.116.102.238:18080
```

## Auth

All Adapter business APIs require a bearer token:

```http
Authorization: Bearer <ADAPTER_API_TOKEN>
```

Local token file for manual calls:

```text
secrets/adapter_api_token.txt
```

Do not paste the token into chat, logs, tickets, or source code.

## Health

```http
GET /health
```

No token required.

Example response:

```json
{"status":"ok"}
```

## Yunxiao Callback Placeholder

```http
POST /callbacks/yunxiao/task
Content-Type: application/json
Authorization: Bearer <ADAPTER_API_TOKEN>
```

### Preview request

```json
{
  "taskId": "yx-task-1001",
  "operator": "zhangsan",
  "hostId": "host-47-116-102-238",
  "execute": false
}
```

### Preview response

```json
{
  "source": "yunxiao",
  "mode": "preview",
  "adapter": {
    "task_id": "yx-task-1001",
    "system": "ssh",
    "action": "check_connectivity",
    "env": "dev",
    "risk": "low",
    "blocked": false
  }
}
```

### Execute request

Execute requires `approvalId` or `approved=true`.

```json
{
  "taskId": "yx-task-1002",
  "operator": "zhangsan",
  "hostId": "host-47-116-102-238",
  "execute": true,
  "approvalId": "manual-approval-1002"
}
```

### Execute response

```json
{
  "source": "yunxiao",
  "mode": "execute",
  "adapter": {
    "task_id": "yx-task-1002",
    "status": "SUCCESS",
    "message": "SSH connectivity check succeeded"
  }
}
```

## Direct Adapter APIs

```http
POST /adapter/preview
POST /adapter/execute
GET /adapter/status/{task_id}
GET /adapter/audit/{task_id}
POST /adapter/dingtalk/read
POST /workflow/start
GET /workflow/{workflow_id}
POST /workflow/{workflow_id}/advance
```

Use the callback endpoint first for Yunxiao integration. Direct Adapter APIs are for manual verification and future system adapters.

## DingTalk / Alidocs Read

```http
POST /adapter/dingtalk/read
Content-Type: application/json
Authorization: Bearer <ADAPTER_API_TOKEN>
```

Reads `alidocs.dingtalk.com/i/nodes/<nodeId>` through Adapter-managed DingTalk OpenAPI calls first. Codex may fall back to OpenClaw / `dws` only when Adapter is unavailable, times out, or returns a read failure, and must state that it is using `OpenClaw fallback`. Browser fetch or web search must not be used for Alidocs links.

The DingTalk app credentials/token cache and document endpoint templates are split into reusable MySQL tables:

```text
adapter_dingtalk_app        # appName/appKey/appSecret/accessToken cache
adapter_dingtalk_doc_config # configName -> appName plus document endpoint templates
```

`adapter_dingtalk_app_config` is legacy compatibility storage only. The default DingTalk app name is `JDB小钉`.

### Request

Use either `url` or `nodeId`. `range` is only used for `axls` spreadsheets. `kind` may be `adoc` or `axls`; if omitted, Adapter uses the configured metadata endpoint to detect it.

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

### Document response

```json
{
  "ok": true,
  "nodeId": "<nodeId>",
  "extension": "adoc",
  "kind": "document",
  "configName": "default",
  "metadata": {},
  "document": {}
}
```

### Spreadsheet response

```json
{
  "ok": true,
  "nodeId": "<nodeId>",
  "extension": "axls",
  "kind": "sheet",
  "configName": "default",
  "metadata": {},
  "sheets": [],
  "sheetId": "<sheetId>",
  "range": "A1:J50",
  "rangeResult": {}
}
```

Configuration helper:

```bash
DINGTALK_APP_KEY='<appKey>' \
DINGTALK_APP_SECRET='<appSecret>' \
DINGTALK_OPERATOR_ID='<operatorUserId>' \
python3 scripts/upsert_dingtalk_config.py --config-name default --app-name 'JDB小钉' \
  --sheet-list-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets?operatorId={operatorIdEncoded}' \
  --sheet-range-url-template 'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}?operatorId={operatorIdEncoded}'
```

Template placeholders: `{nodeId}`, `{sheetId}`, `{range}`, `{operatorId}`, plus `Encoded` variants.

Safety: do not paste appKey, appSecret, bearer tokens, cookies, private keys, auth headers, or Alidocs dashboard URL fragments into chat, logs, tickets, or source code.

## Error Codes

| Code | Meaning |
| --- | --- |
| 400 | DingTalk/Alidocs reader request or DingTalk OpenAPI call failed |
| 401 | Missing bearer token |
| 403 | Invalid bearer token or execute lacks approval |
| 404 | Unknown adapter/system/action |
| 422 | Invalid request body |

## Workflow P0

```http
POST /workflow/start
GET  /workflow/{workflow_id}
POST /workflow/{workflow_id}/advance
POST /workflow/{workflow_id}/requirement
POST /workflow/{workflow_id}/coding-result
Authorization: Bearer <ADAPTER_API_TOKEN>
```

P0 provides a persistent workflow ledger:

- `start` creates a `CREATED` instance from a DingTalk/Alidocs URL.
- `advance` reads the DingTalk document when status is `CREATED` and moves to `DOC_READ`.
- `requirement` stores Codex structured requirement output and moves to `REQUIREMENT_PARSED`.
- `coding-result` stores branch/commit/MR/test summary and moves to `CODE_SUBMITTED`.
- `GET /workflow/{workflow_id}` returns the instance plus recent workflow events.

The workflow tables are:

```text
adapter_workflow_instance
adapter_workflow_event
```

## Audit Log

Remote path:

```text
/opt/adapter-mvp/logs/audit.jsonl
```

Each line is JSON. Passwords and API tokens are not recorded.

When MySQL is configured, status and audit entries are also persisted to:

```text
adapter_status
adapter_audit
adapter_workflow_instance
adapter_workflow_event
```

If the configured DB user cannot create tables, ask DBA to run:

```text
sql/mysql_schema.sql
```

Or initialize with a user that has `CREATE` privilege:

```powershell
python scripts\init_mysql_schema.py --source D:\document\up\mysql.xlsx
```

## Useful Commands

```powershell
.\scripts\call_adapter.ps1 -Mode health
.\scripts\call_adapter.ps1 -Mode preview -TaskId handoff-preview-1
.\scripts\call_adapter.ps1 -Mode execute -TaskId handoff-exec-1 -ApprovalId handoff-approval-1
.\scripts\call_adapter.ps1 -Mode status -TaskId handoff-exec-1
.\scripts\call_adapter.ps1 -Mode audit -TaskId handoff-exec-1
```
