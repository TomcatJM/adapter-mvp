-- 绑定云效流水线 ID 到 Apifox 项目映射。
-- 前置：adapter_apifox_project_config 中已存在 @apifox_project_config_id。

SET @pipeline_id = '<云效流水线ID>';
SET @pipeline_name = 'jdb-demo开发/UAT部署';
SET @service_name = 'jdb-demo';
SET @env_name = 'dev-uat';
SET @repo_name = 'jdb-demo';
SET @apifox_project_config_id = <Apifox项目配置ID>;
SET @pipeline_remark = 'SQL模板初始化Apifox流水线映射';

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
    @pipeline_name,
    @service_name,
    @env_name,
    @repo_name,
    @apifox_project_config_id,
    @pipeline_remark
)
ON DUPLICATE KEY UPDATE
    pipeline_name = VALUES(pipeline_name),
    service_name = VALUES(service_name),
    env_name = VALUES(env_name),
    repo_name = VALUES(repo_name),
    apifox_project_config_id = VALUES(apifox_project_config_id),
    remark = VALUES(remark);
