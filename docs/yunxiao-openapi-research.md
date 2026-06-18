# 云效 HTTP OpenAPI 调研方案

## 1. 结论

云效有官方 HTTP OpenAPI，可以作为 `adapter-mvp` 的主集成方式。

```text
产品：devops
版本：2021-06-25
风格：ROA
公网 Endpoint：devops.cn-hangzhou.aliyuncs.com
鉴权：阿里云 OpenAPI AK 鉴权
官方入口：https://api.aliyun.com/product/devops
```

后续主链路建议走 HTTP/OpenAPI，不走 CLI。CLI 只作为人工调试和参数验证工具。

## 2. 本阶段目标

围绕主规划只调研并实现以下能力：

```text
云效工作项创建
云效工作项关闭/回写
```

不在这个阶段做：

- 大 Agent 框架。
- Skill/MCP/Plugin 化。
- 无关 Adapter 动作扩展。
- 重构已跑通的 workflow P0 / Apifox 链路。

## 3. 已确认官方接口

| 能力 | Action | HTTP | Path | 说明 |
| --- | --- | --- | --- | --- |
| 创建工作项，推荐 | `CreateWorkitemV2` | `POST` | `/organization/{organizationId}/workitem` | 创建需求、缺陷、任务、风险、主题等 |
| 创建工作项，兼容 | `CreateWorkitem` | `POST` | `/organization/{organizationId}/workitems/create` | 老接口，字段名和返回结构不同 |
| 查询工作项详情 | `GetWorkItemInfo` | `GET` | `/organization/{organizationId}/workitems/{workitemId}` | 创建后校验、关单前校验 |
| 查询工作项列表 | `ListWorkitems` | `GET` | 官方列表页已确认 | 幂等反查备用 |
| 创建工作项评论 | `CreateWorkitemComment` | `POST` | `/organization/{organizationId}/workitems/comment` | 回写 MR、流水线、Apifox 同步结果 |
| 更新工作项字段 | `UpdateWorkitemField` | `POST` | `/organization/{organizationId}/workitems/updateWorkitemField` | 批量更新上下文字段和自定义字段 |
| 更新工作项信息 | `UpdateWorkItem` | 官方 Action 已确认 | 官方详情页已确认 | 更新工作项基础信息 |
| 获取项目工作项类型 | `ListProjectWorkitemTypes` | `GET` | `/organization/{organizationId}/projects/{projectId}/getWorkitemType` | 获取 `workitemTypeIdentifier` |
| 获取工作项字段 | `ListWorkItemAllFields` | `GET` | `/organization/{organizationId}/workitems/fields/listAll` | 获取必填字段和选项值 |
| 获取工作流状态 | `ListWorkItemWorkFlowStatus` | `GET` | `/organization/{organizationId}/workitems/workflow/listWorkflowStatus` | 获取关闭/完成状态 identifier |

官方元数据入口格式：

```text
https://api.aliyun.com/meta/v1/products/devops/versions/2021-06-25/overview.json?language=zh_CN
https://api.aliyun.com/meta/v1/products/devops/versions/2021-06-25/apis/{Action}/api.json?language=zh_CN
```

## 4. 创建工作项推荐接口

推荐使用 `CreateWorkitemV2`。

```http
POST https://devops.cn-hangzhou.aliyuncs.com/organization/{organizationId}/workitem
```

必填路径参数：

| 字段 | 说明 |
| --- | --- |
| `organizationId` | 企业标识，可从云效访问链接 `https://devops.aliyun.com/organization/{OrganizationId}` 获取 |

必填 body 字段：

| 字段 | 说明 |
| --- | --- |
| `subject` | 工作项标题 |
| `assignedTo` | 负责人 account id |
| `spaceIdentifier` | 项目唯一标识，同 projectId |
| `category` | 工作项大类，例如 `Req`、`Bug`、`Task`、`Risk` |
| `workitemTypeIdentifier` | 工作项类型 id，从 `ListProjectWorkitemTypes` 获取 |

常用可选 body 字段：

| 字段 | 说明 |
| --- | --- |
| `description` | 工作项描述 |
| `fieldValueList` | 自定义字段值列表 |
| `parentIdentifier` | 父工作项 id |
| `sprintIdentifier` | 迭代 id |
| `tags` | 标签 id 列表 |
| `participants` | 参与人 account id 列表 |
| `trackers` | 抄送人 account id 列表 |
| `verifier` | 验证者 account id |

返回关键字段：

| 字段 | 说明 |
| --- | --- |
| `success` | 是否成功 |
| `workitemIdentifier` | 新建工作项唯一标识 |
| `errorCode` / `errorMessage` | 失败时的业务错误 |

## 5. 字段调研顺序

真实创建前不能猜字段，必须按下面顺序跑一遍：

```text
ListProjects
  -> 确认 projectId / spaceIdentifier
ListProjectWorkitemTypes
  -> category=Req
  -> 确认 workitemTypeIdentifier
ListWorkItemAllFields
  -> spaceType=Project
  -> spaceIdentifier=项目ID
  -> workitemTypeIdentifier=工作项类型ID
  -> 找出 isRequired=true / isSystemRequired=true 的字段
  -> 找出 priority 等字段的 option identifier
ListWorkItemWorkFlowStatus
  -> 确认 “已完成” 等状态 identifier
```

`ListWorkItemAllFields` 关键入参：

| 字段 | 说明 |
| --- | --- |
| `organizationId` | 企业 id |
| `spaceType` | 固定先用 `Project` |
| `spaceIdentifier` | 项目 id |
| `workitemTypeIdentifier` | 工作项类型 id |

返回要重点记录：

| 字段 | 说明 |
| --- | --- |
| `identifier` | 字段唯一标识 |
| `name` | 字段名称 |
| `isRequired` | 是否必填 |
| `isSystemRequired` | 是否系统必填 |
| `options[].identifier` | 列表字段写入时使用的选项 id |
| `options[].displayValue` | 选项展示名 |

## 6. Adapter 字段映射

`adapter-mvp` 创建云效工作项时，建议这样映射：

| Adapter 来源 | 云效字段 | 说明 |
| --- | --- | --- |
| `workflow.context.requirement.summary` | `subject` | 工作项标题 |
| 固定配置 | `assignedTo` | MVP 先用默认负责人 |
| 固定配置 | `spaceIdentifier` | 云效项目 id |
| 固定配置 | `category` | 先用 `Req` |
| 固定配置/调研结果 | `workitemTypeIdentifier` | 需求类型 id |
| 钉钉链接、验收标准、接口变更、测试范围、workflowId | `description` | 描述中禁止放 token/密码 |
| 风险等级/默认优先级 | `fieldValueList` | 通过字段接口确认 priority 字段和选项 id |

描述模板：

```text
来源：钉钉需求文档
Workflow：{workflowId}
钉钉链接：{dingtalkUrl}
仓库：{repoUrl}

需求摘要：
{summary}

验收标准：
- ...

接口变更：
- METHOD PATH 描述

测试范围：
- ...
```

## 7. 工作项创建接入设计

入口复用现有接口：

```http
POST /workflow/{workflow_id}/advance
```

状态流转：

```text
REQUIREMENT_PARSED
  -> CreateWorkitemV2
  -> YUNXIAO_TASK_CREATED
  -> CODING_REQUESTED
```

写入 workflow：

| 字段 | 值 |
| --- | --- |
| `yunxiao_task_id` | `workitemIdentifier` |
| `context.yunxiao.createResult` | 脱敏后的创建结果 |
| `status` | `YUNXIAO_TASK_CREATED` 后再推进到 `CODING_REQUESTED` |

事件：

```text
yunxiao_workitem_created
coding_requested
yunxiao_workitem_create_failed
```

幂等规则：

```text
如果 workflow 已有 yunxiaoTaskId：
  不再调用 CreateWorkitemV2
  直接返回 existing=true
```

MVP 阶段至少做到这个幂等；后续再通过 `workflowId` / `requirementKey` 在云效描述或自定义字段中反查已有工作项。

## 8. 工作项关闭/回写设计

入口状态：

```text
APIFOX_SYNCED
```

推荐顺序：

```text
GetWorkItemInfo
  -> 确认工作项存在且未完成
CreateWorkitemComment
  -> 回写 MR、commit、流水线、Apifox 同步结果
UpdateWorkitemField 或 UpdateWorkItem
  -> 将状态/字段更新为“已完成”
GetWorkItemInfo
  -> 验证最终状态
```

`CreateWorkitemComment`：

```http
POST /organization/{organizationId}/workitems/comment
```

必填 body：

| 字段 | 说明 |
| --- | --- |
| `content` | 评论内容 |
| `workitemIdentifier` | 工作项 id |
| `formatType` | `MARKDOWN` 或 `RICHTEXT` |

`UpdateWorkitemField`：

```http
POST /organization/{organizationId}/workitems/updateWorkitemField
```

必填 body：

| 字段 | 说明 |
| --- | --- |
| `workitemIdentifier` | 工作项 id |
| `updateWorkitemPropertyRequest` | 字段更新数组 |

注意：状态字段到底用 `UpdateWorkitemField` 还是 `UpdateWorkItem`，必须以本企业项目的字段/状态配置和联调结果为准，不能在实现里猜。

## 9. 鉴权和配置

云效 OpenAPI 使用阿里云 OpenAPI AK 鉴权。实现时建议使用官方 SDK / OpenAPI client 完成签名，不手写签名。

MVP 环境变量：

```text
YUNXIAO_OPENAPI_ENDPOINT=devops.cn-hangzhou.aliyuncs.com
YUNXIAO_ORGANIZATION_ID=...
YUNXIAO_PROJECT_ID=...
YUNXIAO_WORKITEM_CATEGORY=Req
YUNXIAO_WORKITEM_TYPE_ID=...
YUNXIAO_WORKITEM_ASSIGNEE=...
YUNXIAO_PRIORITY_FIELD_ID=...
YUNXIAO_PRIORITY_DEFAULT_VALUE=...
YUNXIAO_DONE_STATUS_FIELD_ID=...
YUNXIAO_DONE_STATUS_VALUE=...
```

密钥配置：

```text
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
```

或使用已有运行环境的 STS/RAM 角色。禁止把 AK、token、cookie、Authorization 写入 workflow context、审计 payload 或日志。

## 10. 联调步骤

### 10.1 只读探测

```text
ListProjects
ListProjectWorkitemTypes
ListWorkItemAllFields
ListWorkItemWorkFlowStatus
```

产出配置清单：

```text
organizationId
projectId / spaceIdentifier
workitemTypeIdentifier
required fields
priority field identifier/value
done status identifier/value
assignee account id
```

### 10.2 创建测试工作项

用 `CreateWorkitemV2` 创建标题带测试前缀的工作项：

```text
[Adapter联调] workflow 创建测试
```

创建成功后用 `GetWorkItemInfo` 验证：

```text
identifier
serialNumber
status
statusIdentifier
customFields
```

### 10.3 回写测试

用 `CreateWorkitemComment` 写一条测试评论。

### 10.4 关闭测试

先确认“已完成”状态字段和更新方式，再执行 `UpdateWorkitemField` 或 `UpdateWorkItem`，最后用 `GetWorkItemInfo` 验证。

## 11. 实现建议

建议新增：

```text
app/yunxiao.py
tests/test_yunxiao_workitem_create.py
tests/test_yunxiao_workitem_close.py
```

内部接口：

```python
create_yunxiao_workitem(workflow: dict, operator: str) -> dict
get_yunxiao_workitem(workitem_id: str) -> dict
add_yunxiao_workitem_comment(workitem_id: str, content: str) -> dict
close_yunxiao_workitem(workitem_id: str, context: dict) -> dict
```

优先用官方 SDK/OpenAPI client 发起请求；如果 SDK 引入成本过高，再封装一个独立签名客户端，但不要把签名逻辑散落在 workflow 代码里。

## 12. 风险和待确认

| 风险 | 处理 |
| --- | --- |
| 不同项目必填字段不同 | 必须先跑 `ListWorkItemAllFields`，并把字段落到配置 |
| 状态流转字段不确定 | 必须先跑 `ListWorkItemWorkFlowStatus`，再联调确认更新方式 |
| 负责人 id 类型不一致 | 以云效返回/官方字段为准，统一存 account id |
| 创建超时但云效已创建 | MVP 先避免重复调用已有 `yunxiaoTaskId`，后续用 `workflowId` 反查 |
| AK 权限过大 | 使用最小 RAM 权限，只授予 devops 工作项相关 Action；AK 维护在 `adapter_yunxiao_account_config`，不要进入 workflow context |
| 日志泄密 | 所有响应、异常、审计都做脱敏，不打印 AK、token、Authorization、cookie |

## 13. 下一步

1. 使用阿里云 OpenAPI Explorer 在目标云效项目中跑只读探测。
2. 用 `scripts/upsert_yunxiao_config.py` 固化 `adapter_yunxiao_account_config` 和每个业务项目的 `adapter_yunxiao_project_config`。
3. 使用已实现的 `CreateWorkitemV2` 封装和 workflow `REQUIREMENT_PARSED` 分支联调创建测试工作项。
4. 校验多项目映射不会落到默认项目。
5. 再实现评论和关闭。
