-- 新增或更新钉钉应用和文档读取配置。
-- 修改 appKey/appSecret/auth endpoint 时，会清理旧 access_token 缓存。

SET @dingtalk_config_name = 'default';
SET @dingtalk_app_name = 'JDB小钉';
SET @dingtalk_app_key = '<钉钉AppKey>';
SET @dingtalk_app_secret = '<钉钉AppSecret>';
SET @dingtalk_operator_id = '<钉钉操作人userId>';

START TRANSACTION;

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
