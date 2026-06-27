-- 新增或更新云效项目映射。
-- 前置：adapter_yunxiao_account_config 中已存在 @yunxiao_account_name。

SET @project_name = 'jdb-demo';
SET @yunxiao_account_name = 'yunxiao-main';
SET @yunxiao_organization_id = '<云效组织ID>';
SET @yunxiao_project_id = '<云效项目ID或spaceIdentifier>';
SET @yunxiao_sprint_id = '';
SET @yunxiao_req_type_id = '<云效需求工作项类型ID>';
SET @yunxiao_task_type_id = '<云效任务工作项类型ID>';
SET @yunxiao_default_assignee = '<默认负责人云效账号ID>';
SET @yunxiao_done_status_id = '<已完成状态ID>';
SET @yunxiao_project_remark = 'SQL模板初始化云效项目';

INSERT INTO adapter_yunxiao_project_config (
    project_name,
    account_name,
    account_config_id,
    organization_id,
    project_id,
    sprint_id,
    workitem_category,
    workitem_type_identifier,
    task_workitem_category,
    task_workitem_type_identifier,
    default_assignee,
    done_status_id,
    done_status_field_id,
    done_status_names,
    comment_format_type,
    remark
)
VALUES (
    @project_name,
    @yunxiao_account_name,
    (SELECT id FROM adapter_yunxiao_account_config WHERE account_name = @yunxiao_account_name LIMIT 1),
    @yunxiao_organization_id,
    @yunxiao_project_id,
    NULLIF(@yunxiao_sprint_id, ''),
    'Req',
    @yunxiao_req_type_id,
    'Task',
    @yunxiao_task_type_id,
    @yunxiao_default_assignee,
    NULLIF(@yunxiao_done_status_id, ''),
    'status',
    '已完成,完成,已关闭,done,closed',
    'MARKDOWN',
    @yunxiao_project_remark
)
ON DUPLICATE KEY UPDATE
    account_name = VALUES(account_name),
    account_config_id = VALUES(account_config_id),
    organization_id = VALUES(organization_id),
    project_id = VALUES(project_id),
    sprint_id = VALUES(sprint_id),
    workitem_category = VALUES(workitem_category),
    workitem_type_identifier = VALUES(workitem_type_identifier),
    task_workitem_category = VALUES(task_workitem_category),
    task_workitem_type_identifier = VALUES(task_workitem_type_identifier),
    default_assignee = VALUES(default_assignee),
    done_status_id = VALUES(done_status_id),
    done_status_field_id = VALUES(done_status_field_id),
    done_status_names = VALUES(done_status_names),
    comment_format_type = VALUES(comment_format_type),
    remark = VALUES(remark);
