-- 只新增或更新云效人员，不绑定项目。

SET @member_name = '<负责人姓名>';
SET @member_account_id = '<负责人云效账号ID>';
SET @member_remark = 'SQL模板初始化云效人员';

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
    @member_remark
)
ON DUPLICATE KEY UPDATE
    member_name = VALUES(member_name),
    enabled = VALUES(enabled),
    remark = VALUES(remark);
