-- 新增或更新 Adapter API 调用方。
-- 替换 <...> 占位符后执行。不要提交真实 token。

SET @adapter_client_id = 'codex-local';
SET @adapter_client_name = 'Codex本地调用方';
SET @adapter_client_token = '<Adapter接口调用Token>';
SET @adapter_client_scopes = 'workflow:read,workflow:write';
SET @adapter_client_created_by = 'sql-template';
SET @adapter_client_remark = 'SQL模板初始化Adapter调用方';

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
    @adapter_client_scopes,
    1,
    @adapter_client_created_by,
    @adapter_client_remark
)
ON DUPLICATE KEY UPDATE
    client_name = VALUES(client_name),
    token_hash = VALUES(token_hash),
    token_plaintext = VALUES(token_plaintext),
    scopes = VALUES(scopes),
    enabled = VALUES(enabled),
    created_by = VALUES(created_by),
    remark = VALUES(remark);
