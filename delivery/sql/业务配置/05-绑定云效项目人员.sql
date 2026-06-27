-- 把云效人员绑定到项目；可设为项目默认负责人。
-- 前置：adapter_yunxiao_project_config 中已存在 @project_name。
-- 如果 @is_default = 1，会先取消该项目下其他默认负责人。

SET @project_name = 'jdb-demo';
SET @member_name = '<负责人姓名>';
SET @member_account_id = '<负责人云效账号ID>';
SET @is_default = 1;
SET @member_relation_remark = 'SQL模板初始化项目人员关系';

START TRANSACTION;

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
    @member_relation_remark
)
ON DUPLICATE KEY UPDATE
    member_name = VALUES(member_name),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

UPDATE adapter_yunxiao_project_member_relation
SET is_default = 0
WHERE @is_default = 1
  AND (
      project_config_id = (SELECT id FROM adapter_yunxiao_project_config WHERE project_name = @project_name LIMIT 1)
      OR LOWER(project_name) = LOWER(@project_name)
  );

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
    @is_default,
    1,
    @member_relation_remark
)
ON DUPLICATE KEY UPDATE
    project_config_id = VALUES(project_config_id),
    member_id = VALUES(member_id),
    is_default = VALUES(is_default),
    enabled = VALUES(enabled),
    remark = VALUES(remark);

COMMIT;
