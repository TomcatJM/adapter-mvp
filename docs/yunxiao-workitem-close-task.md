# 云效工作项关闭和回写任务

## 1. 任务目标

在流水线成功且 Apifox 同步成功之后，由 `adapter-mvp` 主动回写并关闭云效工作项。

这个任务只做云效工作项回写/关闭，不做工作项创建，不做流水线绑定，不做 Apifox 导入逻辑本身。

目标状态流转：

```text
APIFOX_SYNCED
  -> 回写发布结果
  -> 关闭云效工作项
  -> YUNXIAO_TASK_CLOSED
```

失败时：

```text
APIFOX_SYNCED
  -> 关闭失败
  -> NEEDS_HUMAN
```

## 2. 当前基础

已存在：

- `scripts/yunxiao_workitem_writeback.sh`
  - 能按 `REQUIREMENT_ID` 和 `CHILD_TASK_IDS` 做脚本级回写。
  - 默认 dry-run，打开 `YUNXIAO_WRITEBACK_ENABLED=true` 才执行。
- `maybe_import_from_flow_event` 已能在云效成功事件后尝试 Apifox 导入。
- workflow 设计中已有 `APIFOX_SYNCED` 和 `YUNXIAO_TASK_CLOSED` 状态。

未完成：

- 服务端云效关闭 adapter。
- Apifox 成功后和 workflow 状态绑定。
- 关闭前检查云效当前状态。
- 关闭失败进入 `NEEDS_HUMAN` 的恢复路径。

## 3. 职责边界

本任务负责：

- 读取 workflow 上的 `yunxiao_task_id`。
- 回写发布结果、流水线信息、Apifox 同步结果。
- 调用云效 OpenAPI 更新/关闭工作项。
- 记录 workflow event。
- 保证重复关闭幂等。

本任务不负责：

- 创建云效工作项。
- 触发或监听流水线。
- 执行 Apifox 导入。
- 解析需求或编码。

## 4. 触发条件

只允许在以下条件满足时关闭：

1. workflow 状态是 `APIFOX_SYNCED`。
2. workflow 存在 `yunxiao_task_id`。
3. workflow context 中有成功的 Apifox 同步结果，或事件表中有 `apifox_synced`。
4. 当前云效工作项不是已关闭状态。

不允许因为“流水线成功”直接关闭。必须经过：

```text
PIPELINE_SUCCESS -> APIFOX_SYNCED -> YUNXIAO_TASK_CLOSED
```

## 5. 建议接口

优先复用：

```http
POST /workflow/{workflow_id}/advance
```

当状态为 `APIFOX_SYNCED` 时，执行云效回写和关闭。

内部函数建议：

```python
close_yunxiao_workitem(workflow: dict, operator: str) -> dict
```

如果需要人工恢复，可后续增加：

```http
POST /workflow/{workflow_id}/resolve
```

用于把 `NEEDS_HUMAN` 恢复到 `APIFOX_SYNCED` 后重试关闭。

## 6. 云效关闭动作拆分

关闭不建议只做一个“改状态”动作，至少分三步：

1. 查询工作项当前状态。
2. 追加评论或更新描述，写入交付结果。
3. 更新状态为完成/已关闭。

建议回写内容：

```text
【Adapter 交付回写】
Workflow：wf-xxx
流水线：pipelineId/buildNumber
分支：feature/xxx
提交：abc123
MR：https://...
Apifox：已同步
结果：SUCCESS
```

回写 payload 禁止包含：

- `ADAPTER_API_TOKEN`
- `YUNXIAO_TOKEN`
- `APIFOX_ACCESS_TOKEN`
- 任何密码、cookie、私钥。

## 7. 配置项

建议复用云效配置：

```text
YUNXIAO_OPENAPI_BASE_URL
YUNXIAO_ORG_ID
YUNXIAO_TOKEN
YUNXIAO_DONE_STATUS_ID
YUNXIAO_WRITEBACK_ENABLED
```

如果云效不同项目的完成状态 ID 不同，建议配置表扩展：

```text
done_status_id
comment_field_key
close_transition_id
```

MVP 阶段可以先用环境变量。

## 8. 幂等规则

必须满足：

1. 如果 workflow 已是 `YUNXIAO_TASK_CLOSED`，重复 advance 直接返回 skipped。
2. 如果云效工作项已是完成状态，Adapter 应补写事件并推进状态，不再报错。
3. 如果评论写入成功但状态更新失败，重试时可以再次写评论，但建议评论内容带 `workflowId`，避免重复难以识别。
4. 如果状态更新成功但 Adapter 写库失败，重试时通过云效当前状态补偿推进 workflow。

最小 MVP 至少做到第 1 和第 2 条。

## 9. 状态和事件

成功事件：

```text
event_type = yunxiao_workitem_closed
from_status = APIFOX_SYNCED
to_status = YUNXIAO_TASK_CLOSED
payload_json = {
  "yunxiaoTaskId": "...",
  "closedStatus": "...",
  "writeback": "success"
}
```

已关闭补偿事件：

```text
event_type = yunxiao_workitem_close_skipped
message = "workitem already closed"
```

失败事件：

```text
event_type = yunxiao_workitem_close_failed
from_status = APIFOX_SYNCED
to_status = NEEDS_HUMAN
last_error = 安全截断后的错误
```

## 10. 失败处理

| 失败类型 | 建议处理 |
| --- | --- |
| 缺少 `yunxiao_task_id` | 进入 `NEEDS_HUMAN`，提示先补绑云效任务 |
| 云效 token 缺失 | 503 或 `NEEDS_HUMAN`，不重试 |
| 云效 4xx | 记录错误，进入 `NEEDS_HUMAN` |
| 云效 5xx / 网络超时 | 保持 `APIFOX_SYNCED` 或进入可重试错误，最多重试 3 次 |
| 工作项已关闭 | 视为成功，推进到 `YUNXIAO_TASK_CLOSED` |

## 11. 验收标准

代码验收：

- `APIFOX_SYNCED` 状态下调用 `/workflow/{id}/advance` 可以关闭云效工作项。
- `YUNXIAO_TASK_CLOSED` 状态下重复调用不会重复关闭。
- 云效已关闭时能补偿推进 workflow。
- 关闭失败不会误报成功。
- 回写内容里不包含密钥。

测试验收：

- 单测覆盖正常关闭。
- 单测覆盖已关闭幂等。
- 单测覆盖缺少 `yunxiao_task_id`。
- 单测覆盖云效 API 失败。
- 单测覆盖 token 不被写入 event payload。

联调验收：

- 使用测试云效工作项完成一次回写和关闭。
- 云效页面能看到 Adapter 回写内容。
- Adapter workflow 查询能看到 `YUNXIAO_TASK_CLOSED`。

## 12. 建议实现文件

建议新增或扩展：

```text
app/yunxiao.py
tests/test_yunxiao_workitem_close.py
```

可能需要扩展：

```text
app/workflow.py
app/db.py
app/models.py
sql/mysql_schema.sql
docs/adapter-api.md
```

注意：不要把现有 `scripts/yunxiao_workitem_writeback.sh` 当作最终实现。它可以作为字段和回写口径参考，但服务端闭环必须落在 Adapter 内部。
