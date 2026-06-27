-- 新增或更新云效鉴权账号。
-- auth_type 支持 acs_ak、personal_token、legacy_token。
-- personal_token / legacy_token 写入 legacy_token 字段；acs_ak 写入 access_key_id / access_key_secret。

SET @yunxiao_account_name = 'yunxiao-main';
SET @yunxiao_auth_type = 'personal_token';
SET @yunxiao_access_key_id = '';
SET @yunxiao_access_key_secret = '';
SET @yunxiao_personal_or_legacy_token = '<云效个人令牌或旧Token>';
SET @yunxiao_security_token = '';
SET @yunxiao_endpoint = 'openapi-rdc.aliyuncs.com';
SET @yunxiao_account_remark = 'SQL模板初始化云效账号';

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
    NULLIF(@yunxiao_personal_or_legacy_token, ''),
    NULLIF(@yunxiao_security_token, ''),
    @yunxiao_endpoint,
    @yunxiao_account_remark
)
ON DUPLICATE KEY UPDATE
    auth_type = VALUES(auth_type),
    access_key_id = VALUES(access_key_id),
    access_key_secret = VALUES(access_key_secret),
    legacy_token = VALUES(legacy_token),
    security_token = VALUES(security_token),
    endpoint = VALUES(endpoint),
    remark = VALUES(remark);
