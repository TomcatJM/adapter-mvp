-- 绑定云效流水线 ID 到 Apifox 项目映射。
-- 前置：adapter_apifox_project_config 中已存在 @project_name。

SET @pipeline_id = '<云效流水线ID>';
SET @project_name = 'jdb-demo';
SET @pipeline_remark = 'SQL模板初始化Apifox流水线映射';

INSERT INTO adapter_apifox_pipeline_config (
    pipeline_id,
    project_name,
    apifox_project_config_id,
    remark
)
VALUES (
    @pipeline_id,
    @project_name,
    (SELECT id FROM adapter_apifox_project_config WHERE project_name = @project_name LIMIT 1),
    @pipeline_remark
)
ON DUPLICATE KEY UPDATE
    project_name = VALUES(project_name),
    apifox_project_config_id = VALUES(apifox_project_config_id),
    remark = VALUES(remark);
