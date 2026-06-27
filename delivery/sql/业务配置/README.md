# Adapter MVP 业务配置 SQL 模板

这些 SQL 用于“部分添加”配置。执行前先确认已执行 `delivery/sql/mysql_schema.sql` 或服务已完成 `ensure_schema`。

使用原则：

- 只新增哪类配置，就执行对应 SQL，不需要执行全量模板。
- 把 `<...>` 占位符替换为真实值后再执行。
- token、AK、Secret 属于敏感信息，不要提交真实值，不要粘贴到聊天或文档。
- 重复执行是幂等的，使用 `INSERT ... ON DUPLICATE KEY UPDATE` 更新已有配置。

文件说明：

| 文件 | 用途 | 会影响的表 |
| --- | --- | --- |
| `01-添加Adapter调用方.sql` | 新增或更新 Adapter API 调用方 token | `adapter_api_client` |
| `02-添加云效账号.sql` | 新增或更新云效鉴权账号 | `adapter_yunxiao_account_config` |
| `03-添加云效项目.sql` | 新增或更新云效项目映射 | `adapter_yunxiao_project_config` |
| `04-添加云效人员.sql` | 只新增或更新人员，不绑定项目 | `adapter_yunxiao_member` |
| `05-绑定云效项目人员.sql` | 把人员绑定到项目，可设为默认负责人 | `adapter_yunxiao_member`、`adapter_yunxiao_project_member_relation` |
| `06-添加Apifox账号.sql` | 新增或更新 Apifox 账号 token | `adapter_apifox_account_config` |
| `07-添加Apifox项目.sql` | 新增或更新 Apifox 项目映射 | `adapter_apifox_project_config` |
| `08-绑定Apifox流水线.sql` | 绑定云效流水线 ID 到 Apifox 项目 | `adapter_apifox_pipeline_config` |
| `09-添加钉钉配置.sql` | 新增或更新钉钉应用和文档读取配置 | `adapter_dingtalk_app`、`adapter_dingtalk_doc_config` |

常见场景：

```sql
-- 只添加人：执行 04-添加云效人员.sql
-- 只添加云效项目：先确保云效账号存在，再执行 03-添加云效项目.sql
-- 给项目增加负责人：执行 05-绑定云效项目人员.sql
-- 给新服务接 Apifox：执行 07-添加Apifox项目.sql，再执行 08-绑定Apifox流水线.sql
```
