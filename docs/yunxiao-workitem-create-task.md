# 云效工作项创建任务

## 1. 任务目标

把 `adapter-mvp` 从“能接云效回调”推进到“能在结构化需求确认后主动创建云效工作项”。

这个任务只做云效工作项创建，不做流水线触发，不做 Apifox 同步，也不做工作项关闭。

目标状态流转：

```text
REQUIREMENT_PARSED
  -> 创建云效主工作项
  -> YUNXIAO_TASK_CREATED
  -> CODING_REQUESTED
```

## 2. 当前基础

已存在：

- workflow P0 基础接口已实现：
  - `POST /workflow/start`
  - `GET /workflow/{workflow_id}`
  - `POST /workflow/{workflow_id}/advance`
  - `POST /workflow/{workflow_id}/requirement`
  - `POST /workflow/{workflow_id}/coding-result`
- `adapter_workflow_instance` 已有 `yunxiao_task_id` 字段。
- `adapter_workflow_event` 已有事件账本。
- `scripts/yunxiao_workitem_writeback.sh` 只是脚本级回写尝试，不能算服务端云效 adapter。

未完成：

- 真实云效项目联调。
- 创建超时后按 `workflowId` / `requirementKey` 反查已有工作项。

## 3. 职责边界

本任务负责：

- 读取 workflow 里的结构化需求。
- 调用云效 OpenAPI 创建主工作项。
- 保存 `yunxiao_task_id`。
- 写 workflow event。
- 返回给 Codex 可继续 coding 的上下文。

本任务不负责：

- 自动让 Codex 写代码。
- 触发云效流水线。
- 处理流水线回调。
- 同步 Apifox。
- 关闭云效工作项。

## 4. 输入和输出

### 4.1 输入

来自 workflow context 的结构化需求：

```json
{
  "workflowId": "wf-xxx",
  "requirement": {
    "summary": "新增客户跟进记录接口",
    "acceptanceCriteria": [
      "支持新增跟进记录",
      "必填字段缺失时返回校验错误"
    ],
    "affectedRepos": ["jdb-school-crm"],
    "apiChanges": [
      {
        "method": "POST",
        "path": "/crm/client/follow-record",
        "description": "新增客户跟进记录"
      }
    ],
    "testScope": ["unit", "api"],
    "risk": "low"
  },
  "repoUrl": "https://codeup.aliyun.com/group/project.git",
  "branchName": "feature/REQ-001",
  "operator": "codex"
}
```

### 4.2 输出

```json
{
  "workflow": {
    "workflowId": "wf-xxx",
    "status": "YUNXIAO_TASK_CREATED",
    "yunxiaoTaskId": "YUNXIAO-123"
  },
  "nextAction": "coding requested"
}
```

如果创建后立即进入可编码状态，也可以推进到：

```text
CODING_REQUESTED
```

建议实现上先明确保留 `YUNXIAO_TASK_CREATED` 事件，再把主状态推进到 `CODING_REQUESTED`；这样账本里能看到工作项创建发生过。

## 5. 建议接口

优先复用：

```http
POST /workflow/{workflow_id}/advance
```

当 workflow 当前状态为 `REQUIREMENT_PARSED` 时，执行创建云效工作项。

不建议 MVP 阶段暴露独立公网接口。内部可以封装函数：

```python
create_yunxiao_workitem(workflow: dict, operator: str) -> dict
```

后面如需调试，再加受保护的 preview 接口：

```http
POST /adapter/yunxiao/workitems/preview
```

## 6. 云效配置

不要把 AK、Secret、token 放到 workflow context。

当前实现使用 DB 优先的配置模型，拆成三张表：

- `adapter_yunxiao_account_config`：维护云效账号鉴权。正式主链路使用 `auth_type=acs_ak` 的阿里云 AK/Secret；兼容历史 OpenClaw CLI 可使用 `auth_type=legacy_token` 的旧云效 token。
- `adapter_yunxiao_project_config`：维护业务项目名到云效 `organization_id`、`project_id`、可选 `sprint_id`、工作项类型等字段的映射，保留 `default_assignee` 作为旧配置兜底。
- `adapter_yunxiao_project_member`：维护项目人员，字段包括姓名、云效账号 ID、是否默认负责人。

```sql
CREATE TABLE adapter_yunxiao_account_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    account_name VARCHAR(128) NOT NULL COMMENT '账号配置名称，例如 default',
    auth_type VARCHAR(32) NOT NULL DEFAULT 'acs_ak' COMMENT '鉴权类型：acs_ak阿里云AK签名，legacy_token旧云效Token',
    access_key_id VARCHAR(256) NULL COMMENT '阿里云AccessKey ID，acs_ak必填',
    access_key_secret VARCHAR(1024) NULL COMMENT '阿里云AccessKey Secret，acs_ak必填',
    legacy_token TEXT NULL COMMENT '旧云效Token，legacy_token必填',
    security_token TEXT NULL COMMENT '临时安全令牌，可选',
    endpoint VARCHAR(256) NOT NULL DEFAULT 'devops.cn-hangzhou.aliyuncs.com' COMMENT '云效OpenAPI Endpoint',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_yunxiao_account_name (account_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效账号AK配置表';

CREATE TABLE adapter_yunxiao_project_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    project_name VARCHAR(128) NOT NULL COMMENT '业务项目名称，例如 jdb-school-crm',
    account_name VARCHAR(128) NOT NULL COMMENT '云效账号配置名称，关联adapter_yunxiao_account_config.account_name',
    organization_id VARCHAR(128) NOT NULL COMMENT '云效企业/组织ID',
    project_id VARCHAR(128) NOT NULL COMMENT '云效项目ID或spaceIdentifier',
    sprint_id VARCHAR(128) NULL COMMENT '云效迭代ID，旧接口可选',
    workitem_category VARCHAR(32) NOT NULL DEFAULT 'Req' COMMENT '云效工作项分类，例如 Req',
    workitem_type_identifier VARCHAR(128) NOT NULL COMMENT '云效工作项类型ID',
    default_assignee VARCHAR(128) NOT NULL COMMENT '默认负责人云效账号ID',
    priority_field_id VARCHAR(128) NULL COMMENT '优先级字段ID，可选',
    priority_default_value VARCHAR(128) NULL COMMENT '默认优先级值，可选',
    participants TEXT NULL COMMENT '参与人，逗号分隔',
    trackers TEXT NULL COMMENT '关注人，逗号分隔',
    verifier VARCHAR(128) NULL COMMENT '验证人云效账号ID',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_yunxiao_project_name (project_name),
    KEY idx_adapter_yunxiao_project_account_name (account_name),
    KEY idx_adapter_yunxiao_project_id (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效项目映射配置表';

CREATE TABLE adapter_yunxiao_project_member (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    project_name VARCHAR(128) NOT NULL COMMENT '业务项目名称，例如 jdb-school-crm',
    member_name VARCHAR(128) NOT NULL COMMENT '负责人姓名，例如 姬志猛',
    yunxiao_account_id VARCHAR(128) NOT NULL COMMENT '云效账号ID',
    is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认负责人：1是，0否',
    enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0停用',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_yunxiao_project_member_name (project_name, member_name),
    UNIQUE KEY uk_adapter_yunxiao_project_member_account (project_name, yunxiao_account_id),
    KEY idx_adapter_yunxiao_project_member_default (project_name, is_default, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效项目人员配置表';
```

项目名解析顺序：

1. `workflow.context.projectName`
2. `workflow.context.requirement.projectName`
3. `workflow.context.requirement.affectedRepos[0]`
4. `workflow.repoUrl` 里的仓库名
5. `YUNXIAO_DEFAULT_PROJECT_NAME`

当 MySQL 已配置时，必须命中 `adapter_yunxiao_project_config`；缺少项目映射会明确失败并记录 `yunxiao_workitem_create_failed`，不会静默落到某个默认云效项目。

无 MySQL 的本地开发环境仍保留 env 兜底：

```text
ALIBABA_CLOUD_ACCESS_KEY_ID
ALIBABA_CLOUD_ACCESS_KEY_SECRET
YUNXIAO_ORGANIZATION_ID
YUNXIAO_PROJECT_ID
YUNXIAO_WORKITEM_TYPE_IDENTIFIER
YUNXIAO_WORKITEM_ASSIGNEE
```

推荐用脚本维护配置，AK 从环境变量读取，脚本不会打印 AK/Secret：

```bash
ALIBABA_CLOUD_ACCESS_KEY_ID=xxx \
ALIBABA_CLOUD_ACCESS_KEY_SECRET=yyy \
python scripts/upsert_yunxiao_config.py \
  --account-name default \
  --project-name jdb-school-crm \
  --organization-id <云效组织ID> \
  --project-id <云效项目ID或spaceIdentifier> \
  --workitem-type-identifier <工作项类型ID> \
  --default-assignee <负责人云效账号ID> \
  --member-name <负责人姓名> \
  --member-account-id <负责人云效账号ID> \
  --member-default
```

历史 OpenClaw CLI 配置可以导入为兼容账号，脚本不会打印 token：

```bash
python scripts/upsert_yunxiao_config.py \
  --auth-type legacy_token \
  --account-name legacy-openclaw \
  --legacy-config /root/.openclaw/yunxiao-task-config.json \
  --project-name jdb-school-crm \
  --project-id <云效项目ID或spaceIdentifier> \
  --sprint-id <云效迭代ID> \
  --default-assignee <负责人云效账号ID> \
  --member-name <负责人姓名> \
  --member-account-id <负责人云效账号ID> \
  --member-default
```

只维护人员表时不需要重新写账号或项目映射：

```bash
python scripts/upsert_yunxiao_config.py \
  --member-only \
  --project-name jdb-school-crm \
  --member-name 姬志猛 \
  --member-account-id <负责人云效账号ID> \
  --member-default
```

## 7. 工作项字段映射

| 云效字段 | 来源 | 说明 |
| --- | --- | --- |
| 标题 | `requirement.summary` | 必填 |
| 描述 | 钉钉链接、验收标准、接口变更、测试范围 | 不放密钥 |
| 负责人 | `assigneeId` / `assigneeName`，否则项目默认负责人 | 优先查 `adapter_yunxiao_project_member`；旧 `default_assignee` 只做兜底 |
| 关联链接 | `dingtalkUrl`、MR URL 预留 | 创建阶段先放钉钉链接 |
| 优先级 | `requirement.risk` 或 context | 无映射时默认普通 |
| 标签 | `adapter-mvp`、项目名 | 便于筛选 |

描述建议包含：

```text
来源：钉钉需求文档
Workflow：wf-xxx
仓库：jdb-school-crm
验收标准：
- ...
接口变更：
- POST /xxx
```

## 8. 幂等规则

必须满足：

1. 如果 workflow 已有 `yunxiao_task_id`，重复 advance 不能重复创建。
2. 如果创建请求超时但后续查询发现已创建，应补写 `yunxiao_task_id`。
3. 推荐用 `workflow_id` 或 `requirement_key` 写入云效工作项描述/自定义字段，方便反查。
4. 创建成功但写库失败时，重试需要能按 `workflow_id` 找回已有工作项。

最小 MVP 可以先做到第 1 条，后续补第 2-4 条。

## 9. 状态和事件

成功事件：

```text
event_type = yunxiao_workitem_created
from_status = REQUIREMENT_PARSED
to_status = YUNXIAO_TASK_CREATED
payload_json = {
  "yunxiaoTaskId": "...",
  "projectId": "...",
  "title": "..."
}
```

如果随后自动进入 coding：

```text
event_type = coding_requested
from_status = YUNXIAO_TASK_CREATED
to_status = CODING_REQUESTED
```

失败事件：

```text
event_type = yunxiao_workitem_create_failed
status 保持 REQUIREMENT_PARSED
last_error = 安全截断后的错误
```

## 10. 验收标准

当前实现状态：代码验收和单测验收已完成；真实云效项目联调待补云效 OpenAPI 配置后执行。

代码验收：

- [x] `REQUIREMENT_PARSED` 状态下调用 `/workflow/{id}/advance` 可以创建云效工作项。
- [x] 创建成功后 workflow 保存 `yunxiaoTaskId`。
- [x] 重复调用不会重复创建。
- [x] AK 和多项目云效配置已落到 `adapter_yunxiao_account_config` / `adapter_yunxiao_project_config`。
- [x] MySQL 已配置时，缺少项目映射会明确失败，不会静默使用默认项目。
- [x] 创建失败不会把状态推进到成功状态。
- [x] 审计/事件里不出现 token、cookie、密码。

测试验收：

- [x] 单测覆盖成功创建。
- [x] 单测覆盖已有 `yunxiao_task_id` 时跳过创建。
- [x] 单测覆盖云效 API 失败。
- [x] 单测覆盖配置缺失时明确失败。

联调验收：

- 使用测试云效项目创建一个真实工作项。
- 云效工作项描述里能看到 workflowId、钉钉链接、验收标准。
- Adapter 查询 workflow 能看到 `YUNXIAO_TASK_CREATED` 或 `CODING_REQUESTED`。

## 11. 建议实现文件

建议新增：

```text
app/yunxiao.py
tests/test_yunxiao_workitem_create.py
```

可能需要扩展：

```text
app/workflow.py
app/db.py
app/models.py
sql/mysql_schema.sql
docs/adapter-api.md
```

注意：开始实现前先看 `git status` 和当前 diff，避免覆盖并行会话或未提交改动。
