# Coding Spec 模板

> 用途：Codex / AI 在实际改代码前，把钉钉需求、云效任务、知识图谱和 CodeGraph 影响面整理成可执行编码说明。

## 1. 任务来源

```text
workflowId: <Adapter workflow ID>
projectKey: <Adapter project key>
yunxiaoDemandId: <云效需求 ID，可为空>
yunxiaoTaskIds: <云效任务 ID 列表>
requirementTitle: <需求标题>
sourceUrl: <钉钉文档链接>
targetBranch: <目标分支>
```

## 2. 需求摘要

```text
背景：
<业务背景和目标>

本次要做：
1. <事项一>
2. <事项二>

不做：
1. <明确排除事项>
```

## 3. 上下文依据

### 3.1 业务知识

```text
知识图谱摘要：
<来自 knowledgeContext.businessKnowledge.summary>

关键业务规则：
- <规则一>
- <规则二>

相关文档：
- <文档或知识节点引用>
```

### 3.2 代码影响面

```text
CodeGraph 索引：
branchName: <branch>
commitId: <commit>
indexVersion: <indexVersion>

直接影响文件：
- <file>

上游调用：
- <caller>

下游依赖：
- <callee>

风险提示：
- <risk>
```

## 4. 实现计划

```text
1. <先改模型/DTO/配置等>
2. <再改业务逻辑>
3. <再改接口/脚本/文档>
4. <最后补测试>
```

要求：

- 优先复用现有模块和工具函数。
- 不引入无关依赖。
- 不做需求外重构。
- 不用静默默认项目、默认负责人、默认迭代或默认 Apifox 项目掩盖配置缺失。

## 5. 文件清单

| 文件 | 操作 | 原因 |
| --- | --- | --- |
| `<path>` | 新增/修改/删除 | `<原因>` |

## 6. 测试计划

```text
单测：
- <测试文件 / 测试场景>

静态检查：
- .venv/bin/python -m compileall app scripts

回归：
- <主链路或接口回归场景>
```

## 7. 验收标准

- [ ] 功能行为满足钉钉需求和云效任务描述。
- [ ] 业务规则和知识图谱上下文一致。
- [ ] CodeGraph 影响面中列出的关键入口已检查。
- [ ] 相关测试通过。
- [ ] 不打印 token、AK、SK、Authorization、cookie 或私钥。
- [ ] 文档或配置清单已同步需要维护的新增配置。

## 8. 提交说明草稿

```text
<type>: <summary>

云效任务: <task ids>
workflowId: <workflow id>
projectKey: <project key>
```

