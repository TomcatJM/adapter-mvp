<!-- ADAPTER-MVP-GUARD:START -->
# Adapter MVP Execution Rules

本项目处理钉钉需求文档、云效工作项、流水线回调和 Apifox 同步时，必须先遵守这些规则。

## 强制业务模型

- 云效“需求”和“任务”是两类工作项，不能混用。
- 钉钉需求文档解析后，先创建云效需求，再在对应需求下创建云效任务。
- 云效任务必须挂到父需求下：personal token 链路使用 `parentId`，Adapter context 使用 `parentIdentifier` 留痕。
- 需求标题是作用域边界：某个需求标题下面的描述、负责人、主要内容和任务，只能归属当前需求。
- `demandIndex` / `itemIndex` 只表示顺序，不能用来推断、借用或覆盖需求标题。
- 需求标题缺失或归属不明确时必须失败或请用户确认，不能从文档标题、需求键、第一条需求或其他需求静默推断。
- 钉钉文档里的版本号必须映射到云效迭代；匹配不到唯一迭代时必须失败，不允许静默置空。
- 关单只关闭提交信息里 `云效任务` 显式列出的真实子任务，不关闭需求；如果提交信息没有 `云效任务` ID，必须跳过关单，不允许默认关闭全部任务；手动补救只能通过 `closeTaskRefs` 传同一类任务 ID。
- webhook 解析提交信息时，不能只识别固定英文键；应兼容 `云效ID`、`云效任务`、`任务编号`、`yunxiaoTaskDisplayId` 等用户可见写法。
- 解析产品钉钉需求文档前，必须先对齐 `delivery/templates/钉钉需求文档标准模版.md`；如果文档出现新格式，先沉淀或补充模版样式，再继续解析和创建云效工作项。
- 钉钉文档里的项目名只按 `adapter_yunxiao_project_config.project_name` 校验和解析；不能从 Apifox 项目名、流水线项目名或代码仓库名反推。未匹配时必须列出 DB 中可选云效项目名。
- 钉钉文档里的任务负责人如果非空，必须命中 `adapter_yunxiao_member` + `adapter_yunxiao_project_member_relation`；未命中时必须失败并列出项目已配置人员，不能改用默认负责人。只有负责人为空时才允许使用项目默认负责人。

## 修改代码前后要求

- 修改前先确认当前测试覆盖点，优先补回归测试再改实现。
- 修改云效创建、关单、流水线绑定、Apifox 同步相关逻辑后，必须运行对应单测和 `compileall`。
- 不允许打印 token、AK、密码、Authorization、cookie 或私钥。
- 不允许用静默默认项目、默认 Apifox 项目、空迭代、空负责人掩盖配置缺失。
- 本仓库后续所有 Git commit message 必须使用中文，不允许只使用英文提交信息。

## 推荐校验命令

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall app scripts
.venv/bin/python scripts/validate_yunxiao_workflow_guard.py --file <workflow.json> --mode all
```
<!-- ADAPTER-MVP-GUARD:END -->
