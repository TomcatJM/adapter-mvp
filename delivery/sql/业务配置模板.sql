-- Adapter MVP 业务配置数据模板
-- 用途：初始化或新增 Adapter 调用方、云效、Apifox、钉钉相关配置。
-- 注意：
-- 1. 执行前先确认已执行 delivery/sql/mysql_schema.sql 或服务已完成 ensure_schema。
-- 2. 把所有 <...> 占位符替换为真实值后再执行。
-- 3. token、AK、Secret 属于敏感信息；不要提交真实值，不要粘贴到聊天或文档。
-- 4. 如果某项暂不需要，删除对应 INSERT 段即可。

START TRANSACTION;

-- ============================================================
-- 0. 通用变量：按实际项目替换
-- ============================================================
SET @adapter_client_id = 'codex-local';
SET @adapter_client_name = 'Codex本地调用方';
SET @adapter_client_token = '<Adapter接口调用Token>';

SET @yunxiao_account_name = 'yunxiao-main';
SET @yunxiao_auth_type = 'personal_token';
SET @yunxiao_access_key_id = '';
SET @yunxiao_access_key_secret = '';
SET @yunxiao_personal_token = '<云效个人令牌或旧Token>';
SET @yunxiao_endpoint = 'openapi-rdc.aliyuncs.com';

SET @project_name = 'jdb-demo';
SET @yunxiao_organization_id = '<云效组织ID>';
SET @yunxiao_project_id = '<云效项目ID>';
SET @yunxiao_sprint_id = '';
SET @yunxiao_req_type_id = '<云效需求工作项类型ID>';
SET @yunxiao_task_type_id = '<云效任务工作项类型ID>';
SET @yunxiao_default_assignee = '<默认负责人云效账号ID>';
SET @yunxiao_done_status_id = '<已完成状态ID>';

SET @member_name = '<负责人姓名>';
SET @member_account_id = '<负责人云效账号ID>';

SET @apifox_account_name = 'apifox-main';
SET @apifox_access_token = '<Apifox Access Token>';
SET @apifox_project_id = '<Apifox项目ID>';
SET @openapi_url = 'http://47.116.102.238:18080/adapter/openapi/jdb-demo';
SET @pipeline_id = '<云效流水线ID>';

SET @dingtalk_config_name = 'default';
SET @dingtalk_app_name = 'JDB小钉';
SET @dingtalk_app_key = '<钉钉AppKey>';
SET @dingtalk_app_secret = '<钉钉AppSecret>';
SET @dingtalk_operator_id = '<钉钉操作人userId>';

-- ============================================================
-- 1. Adapter 调用方：adapter_api_client
-- ============================================================
INSERT INTO adapter_api_client (
    client_id,
    client_name,
    token_hash,
    token_plaintext,
    scopes,
    enabled,
    created_by,
    remark
)
VALUES (
    @adapter_client_id,
    @adapter_client_name,
    SHA2(@adapter_client_token, 256),
    @adapter_client_token,
    'workflow:read,workflow:write',
    1,
    'sql-template',
    'SQL模板初始化'
)
ON DUPLICATE KEY UPDATE
    client_name = VALUES(client_name),
    token_hash = VALUES(token_hash),
    token_plaintext = VALUES(token_plaintext),
    scopes = VALUES(scopes),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

-- ============================================================
-- 2. 云效账号：adapter_yunxiao_account_config
-- ============================================================
INSERT INTO adapter_yunxiao_account_config (
    account_name,
    auth_type,
    access_key_id,
    access_key_secret,
    legacy_token,
    security_token,
    endpoint,
    remark
)
VALUES (
    @yunxiao_account_name,
    @yunxiao_auth_type,
    NULLIF(@yunxiao_access_key_id, ''),
    NULLIF(@yunxiao_access_key_secret, ''),
    NULLIF(@yunxiao_personal_token, ''),
    NULL,
    @yunxiao_endpoint,
    'SQL模板初始化云效账号'
)
ON DUPLICATE KEY UPDATE
    auth_type = VALUES(auth_type),
    access_key_id = VALUES(access_key_id),
    access_key_secret = VALUES(access_key_secret),
    legacy_token = VALUES(legacy_token),
    security_token = VALUES(security_token),
    endpoint = VALUES(endpoint),
    remark = VALUES(remark);

-- ============================================================
-- 3. 云效项目：adapter_yunxiao_project_config
-- ============================================================
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
    'SQL模板初始化云效项目'
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

-- ============================================================
-- 4. 云效人员和项目负责人：adapter_yunxiao_member / adapter_yunxiao_project_member_relation
-- ============================================================
INSERT INTO adapter_yunxiao_member (
    member_name,
    yunxiao_account_id,
    enabled,
    remark
)
VALUES (
    @member_name,
    @member_account_id,
    1,
    'SQL模板初始化云效人员'
)
ON DUPLICATE KEY UPDATE
    member_name = VALUES(member_name),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

UPDATE adapter_yunxiao_project_member_relation
SET is_default = 0
WHERE project_config_id = (SELECT id FROM adapter_yunxiao_project_config WHERE project_name = @project_name LIMIT 1)
   OR LOWER(project_name) = LOWER(@project_name);

INSERT INTO adapter_yunxiao_project_member_relation (
    project_name,
    project_config_id,
    yunxiao_account_id,
    member_id,
    is_default,
    enabled,
    remark
)
VALUES (
    @project_name,
    (SELECT id FROM adapter_yunxiao_project_config WHERE project_name = @project_name LIMIT 1),
    @member_account_id,
    (SELECT id FROM adapter_yunxiao_member WHERE yunxiao_account_id = @member_account_id LIMIT 1),
    1,
    1,
    'SQL模板初始化项目默认负责人'
)
ON DUPLICATE KEY UPDATE
    project_config_id = VALUES(project_config_id),
    member_id = VALUES(member_id),
    is_default = VALUES(is_default),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

-- ============================================================
-- 5. Apifox账号和项目：adapter_apifox_account_config / adapter_apifox_project_config
-- ============================================================
INSERT INTO adapter_apifox_account_config (
    account_name,
    access_token,
    enabled,
    remark
)
VALUES (
    @apifox_account_name,
    @apifox_access_token,
    1,
    'SQL模板初始化Apifox账号'
)
ON DUPLICATE KEY UPDATE
    access_token = VALUES(access_token),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

INSERT INTO adapter_apifox_project_config (
    project_name,
    account_name,
    account_config_id,
    apifox_project_id,
    openapi_url,
    remark
)
VALUES (
    @project_name,
    @apifox_account_name,
    (SELECT id FROM adapter_apifox_account_config WHERE account_name = @apifox_account_name LIMIT 1),
    @apifox_project_id,
    @openapi_url,
    'SQL模板初始化Apifox项目'
)
ON DUPLICATE KEY UPDATE
    account_name = VALUES(account_name),
    account_config_id = VALUES(account_config_id),
    apifox_project_id = VALUES(apifox_project_id),
    openapi_url = VALUES(openapi_url),
    remark = VALUES(remark);

-- ============================================================
-- 6. Apifox流水线映射：adapter_apifox_pipeline_config
-- ============================================================
INSERT INTO adapter_apifox_pipeline_config (
    pipeline_id,
    pipeline_name,
    service_name,
    env_name,
    repo_name,
    apifox_project_config_id,
    remark
)
VALUES (
    @pipeline_id,
    CONCAT(@project_name, '开发/UAT部署'),
    @project_name,
    'dev-uat',
    @project_name,
    (SELECT id FROM adapter_apifox_project_config WHERE project_name = @project_name LIMIT 1),
    'SQL模板初始化流水线映射'
)
ON DUPLICATE KEY UPDATE
    pipeline_name = VALUES(pipeline_name),
    service_name = VALUES(service_name),
    env_name = VALUES(env_name),
    repo_name = VALUES(repo_name),
    apifox_project_config_id = VALUES(apifox_project_config_id),
    remark = VALUES(remark);

-- ============================================================
-- 7. 钉钉应用和文档读取配置：adapter_dingtalk_app / adapter_dingtalk_doc_config
-- ============================================================
INSERT INTO adapter_dingtalk_app (
    app_name,
    app_key,
    app_secret,
    auth_endpoint,
    token_header_name,
    remark
)
VALUES (
    @dingtalk_app_name,
    @dingtalk_app_key,
    @dingtalk_app_secret,
    'https://api.dingtalk.com/v1.0/oauth2/accessToken',
    'x-acs-dingtalk-access-token',
    'SQL模板初始化钉钉应用'
)
ON DUPLICATE KEY UPDATE
    access_token = CASE
        WHEN app_key <> VALUES(app_key)
          OR app_secret <> VALUES(app_secret)
          OR auth_endpoint <> VALUES(auth_endpoint)
        THEN NULL
        ELSE access_token
    END,
    token_expires_at = CASE
        WHEN app_key <> VALUES(app_key)
          OR app_secret <> VALUES(app_secret)
          OR auth_endpoint <> VALUES(auth_endpoint)
        THEN NULL
        ELSE token_expires_at
    END,
    app_key = VALUES(app_key),
    app_secret = VALUES(app_secret),
    auth_endpoint = VALUES(auth_endpoint),
    token_header_name = VALUES(token_header_name),
    remark = VALUES(remark);

INSERT INTO adapter_dingtalk_doc_config (
    config_name,
    app_name,
    operator_id,
    doc_info_method,
    doc_info_url_template,
    doc_info_body_template,
    doc_read_method,
    doc_read_url_template,
    doc_read_body_template,
    sheet_list_method,
    sheet_list_url_template,
    sheet_list_body_template,
    sheet_range_method,
    sheet_range_url_template,
    sheet_range_body_template,
    remark
)
VALUES (
    @dingtalk_config_name,
    @dingtalk_app_name,
    @dingtalk_operator_id,
    'GET',
    'https://api.dingtalk.com/v2.0/wiki/nodes/{nodeIdEncoded}?withStatisticalInfo=false&withPermissionRole=false&operatorId={operatorIdEncoded}',
    NULL,
    'GET',
    NULL,
    NULL,
    'GET',
    'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets?operatorId={operatorIdEncoded}',
    NULL,
    'GET',
    'https://api.dingtalk.com/v1.0/doc/workbooks/{nodeId}/sheets/{sheetIdEncoded}/ranges/{rangeEncoded}?operatorId={operatorIdEncoded}',
    NULL,
    'SQL模板初始化钉钉文档读取配置'
)
ON DUPLICATE KEY UPDATE
    app_name = VALUES(app_name),
    operator_id = VALUES(operator_id),
    doc_info_method = VALUES(doc_info_method),
    doc_info_url_template = VALUES(doc_info_url_template),
    doc_info_body_template = VALUES(doc_info_body_template),
    doc_read_method = VALUES(doc_read_method),
    doc_read_url_template = VALUES(doc_read_url_template),
    doc_read_body_template = VALUES(doc_read_body_template),
    sheet_list_method = VALUES(sheet_list_method),
    sheet_list_url_template = VALUES(sheet_list_url_template),
    sheet_list_body_template = VALUES(sheet_list_body_template),
    sheet_range_method = VALUES(sheet_range_method),
    sheet_range_url_template = VALUES(sheet_range_url_template),
    sheet_range_body_template = VALUES(sheet_range_body_template),
    remark = VALUES(remark);

COMMIT;
