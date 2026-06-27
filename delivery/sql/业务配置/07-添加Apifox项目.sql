-- 新增或更新 Apifox 项目映射。
-- 前置：如需使用 DB token，adapter_apifox_account_config 中应存在 @apifox_account_name。

SET @project_name = 'jdb-demo';
SET @apifox_account_name = 'apifox-main';
SET @apifox_project_id = '<Apifox项目ID>';
SET @openapi_url = 'http://47.116.102.238:18080/adapter/openapi/jdb-demo';
SET @apifox_project_remark = 'SQL模板初始化Apifox项目';

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
    @apifox_project_remark
)
ON DUPLICATE KEY UPDATE
    account_name = VALUES(account_name),
    account_config_id = VALUES(account_config_id),
    apifox_project_id = VALUES(apifox_project_id),
    openapi_url = VALUES(openapi_url),
    remark = VALUES(remark);
