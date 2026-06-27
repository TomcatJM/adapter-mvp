-- 新增或更新 Apifox 账号 token。

SET @apifox_account_name = 'apifox-main';
SET @apifox_access_token = '<Apifox Access Token>';
SET @apifox_account_remark = 'SQL模板初始化Apifox账号';

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
    @apifox_account_remark
)
ON DUPLICATE KEY UPDATE
    access_token = VALUES(access_token),
    enabled = VALUES(enabled),
    remark = VALUES(remark);
