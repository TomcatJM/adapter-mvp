CREATE TABLE IF NOT EXISTS adapter_status (
    task_id VARCHAR(128) PRIMARY KEY COMMENT '任务ID',
    status VARCHAR(64) NOT NULL COMMENT '任务状态：SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知',
    message VARCHAR(1024) NOT NULL COMMENT '状态说明',
    data_json JSON NULL COMMENT '安全结果数据JSON',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter任务状态表';

CREATE TABLE IF NOT EXISTS adapter_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件时间',
    event VARCHAR(64) NOT NULL COMMENT '事件类型：preview预览，execute执行，status状态查询',
    task_id VARCHAR(128) NULL COMMENT '任务ID',
    operator VARCHAR(128) NULL COMMENT '操作人',
    system_name VARCHAR(64) NULL COMMENT '适配系统',
    action_name VARCHAR(128) NULL COMMENT '适配动作',
    env_name VARCHAR(64) NULL COMMENT '环境',
    host_id VARCHAR(128) NULL COMMENT '主机ID',
    approval_id VARCHAR(128) NULL COMMENT '审批ID',
    approved TINYINT(1) NULL COMMENT '是否显式审批：1是，0否',
    status VARCHAR(64) NULL COMMENT '执行状态：PREVIEWED已预览，BLOCKED已阻断，SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知',
    message VARCHAR(1024) NULL COMMENT '执行说明',
    elapsed_ms INT NULL COMMENT '耗时毫秒',
    payload_json JSON NULL COMMENT '安全审计载荷JSON',
    KEY idx_adapter_audit_task_id (task_id),
    KEY idx_adapter_audit_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter审计日志表';

CREATE TABLE IF NOT EXISTS adapter_apifox_project_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
    apifox_project_id VARCHAR(64) NOT NULL COMMENT 'Apifox项目ID',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_apifox_project_name (project_name),
    KEY idx_adapter_apifox_project_id (apifox_project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox项目映射配置表';

CREATE TABLE IF NOT EXISTS adapter_apifox_pipeline_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    pipeline_id VARCHAR(64) NOT NULL COMMENT '云效流水线ID',
    project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_apifox_pipeline_id (pipeline_id),
    KEY idx_adapter_apifox_pipeline_project_name (project_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox流水线项目映射配置表';

CREATE TABLE IF NOT EXISTS adapter_dingtalk_app_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    config_name VARCHAR(128) NOT NULL COMMENT '配置名称，例如 default',
    app_key VARCHAR(128) NOT NULL COMMENT '钉钉应用AppKey',
    app_secret VARCHAR(512) NOT NULL COMMENT '钉钉应用AppSecret',
    auth_endpoint VARCHAR(1024) NOT NULL DEFAULT 'https://api.dingtalk.com/v1.0/oauth2/accessToken' COMMENT '获取access_token的接口地址',
    token_header_name VARCHAR(128) NOT NULL DEFAULT 'x-acs-dingtalk-access-token' COMMENT '业务接口token请求头名称',
    operator_id VARCHAR(128) NULL COMMENT '钉钉文档操作人userId',
    doc_info_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '文档元数据接口HTTP方法',
    doc_info_url_template VARCHAR(2048) NULL COMMENT '文档元数据接口URL模板',
    doc_info_body_template JSON NULL COMMENT '文档元数据接口JSON请求体模板',
    doc_read_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '文档正文接口HTTP方法',
    doc_read_url_template VARCHAR(2048) NULL COMMENT '文档正文接口URL模板',
    doc_read_body_template JSON NULL COMMENT '文档正文接口JSON请求体模板',
    sheet_list_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '表格sheet列表接口HTTP方法',
    sheet_list_url_template VARCHAR(2048) NULL COMMENT '表格sheet列表接口URL模板',
    sheet_list_body_template JSON NULL COMMENT '表格sheet列表接口JSON请求体模板',
    sheet_range_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '表格range读取接口HTTP方法',
    sheet_range_url_template VARCHAR(2048) NULL COMMENT '表格range读取接口URL模板',
    sheet_range_body_template JSON NULL COMMENT '表格range读取接口JSON请求体模板',
    access_token TEXT NULL COMMENT 'Adapter缓存的钉钉access_token',
    token_expires_at DATETIME NULL COMMENT 'access_token过期时间',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_dingtalk_config_name (config_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉文档读取旧版混合配置表';

CREATE TABLE IF NOT EXISTS adapter_dingtalk_app (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    app_name VARCHAR(128) NOT NULL COMMENT '钉钉应用名称，例如 JDB小钉',
    app_key VARCHAR(128) NOT NULL COMMENT '钉钉应用AppKey',
    app_secret VARCHAR(512) NOT NULL COMMENT '钉钉应用AppSecret',
    auth_endpoint VARCHAR(1024) NOT NULL DEFAULT 'https://api.dingtalk.com/v1.0/oauth2/accessToken' COMMENT '获取access_token的接口地址',
    token_header_name VARCHAR(128) NOT NULL DEFAULT 'x-acs-dingtalk-access-token' COMMENT '业务接口token请求头名称',
    access_token TEXT NULL COMMENT 'Adapter缓存的钉钉access_token',
    token_expires_at DATETIME NULL COMMENT 'access_token过期时间',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_dingtalk_app_name (app_name),
    KEY idx_adapter_dingtalk_app_key (app_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉应用表';

CREATE TABLE IF NOT EXISTS adapter_dingtalk_doc_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    config_name VARCHAR(128) NOT NULL COMMENT '配置名称，例如 default',
    app_name VARCHAR(128) NOT NULL COMMENT '钉钉应用名称，关联adapter_dingtalk_app.app_name',
    operator_id VARCHAR(128) NULL COMMENT '钉钉文档操作人userId',
    doc_info_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '文档元数据接口HTTP方法',
    doc_info_url_template VARCHAR(2048) NULL COMMENT '文档元数据接口URL模板',
    doc_info_body_template JSON NULL COMMENT '文档元数据接口JSON请求体模板',
    doc_read_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '文档正文接口HTTP方法',
    doc_read_url_template VARCHAR(2048) NULL COMMENT '文档正文接口URL模板',
    doc_read_body_template JSON NULL COMMENT '文档正文接口JSON请求体模板',
    sheet_list_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '表格sheet列表接口HTTP方法',
    sheet_list_url_template VARCHAR(2048) NULL COMMENT '表格sheet列表接口URL模板',
    sheet_list_body_template JSON NULL COMMENT '表格sheet列表接口JSON请求体模板',
    sheet_range_method VARCHAR(16) NOT NULL DEFAULT 'GET' COMMENT '表格range读取接口HTTP方法',
    sheet_range_url_template VARCHAR(2048) NULL COMMENT '表格range读取接口URL模板',
    sheet_range_body_template JSON NULL COMMENT '表格range读取接口JSON请求体模板',
    remark VARCHAR(512) NULL COMMENT '备注',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_dingtalk_doc_config_name (config_name),
    KEY idx_adapter_dingtalk_doc_app_name (app_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉文档读取配置表';

CREATE TABLE IF NOT EXISTS adapter_workflow_instance (
    workflow_id VARCHAR(64) PRIMARY KEY COMMENT '工作流实例ID',
    requirement_key VARCHAR(128) NULL COMMENT '需求唯一键，可来自钉钉节点或云效工作项',
    dingtalk_url VARCHAR(2048) NOT NULL COMMENT '钉钉/Alidocs需求文档URL',
    dingtalk_node_id VARCHAR(256) NULL COMMENT '钉钉文档节点ID',
    yunxiao_task_id VARCHAR(128) NULL COMMENT '云效主任务ID',
    yunxiao_pipeline_id VARCHAR(128) NULL COMMENT '云效流水线ID',
    yunxiao_build_number VARCHAR(128) NULL COMMENT '云效构建号',
    repo_url VARCHAR(1024) NULL COMMENT '代码仓库地址',
    branch_name VARCHAR(256) NULL COMMENT '实现分支',
    commit_id VARCHAR(128) NULL COMMENT '提交ID',
    apifox_project_id VARCHAR(128) NULL COMMENT 'Apifox项目ID',
    status VARCHAR(64) NOT NULL COMMENT '工作流状态',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '当前步骤重试次数',
    last_error VARCHAR(2048) NULL COMMENT '最近错误',
    context_json JSON NULL COMMENT '安全上下文JSON',
    created_by VARCHAR(128) NULL COMMENT '创建人',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_adapter_workflow_requirement_key (requirement_key),
    KEY idx_adapter_workflow_status (status),
    KEY idx_adapter_workflow_yunxiao_task_id (yunxiao_task_id),
    KEY idx_adapter_workflow_pipeline (yunxiao_pipeline_id, yunxiao_build_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter交付工作流实例表';

CREATE TABLE IF NOT EXISTS adapter_workflow_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
    workflow_id VARCHAR(64) NOT NULL COMMENT '工作流实例ID',
    event_type VARCHAR(64) NOT NULL COMMENT '事件类型',
    from_status VARCHAR(64) NULL COMMENT '变更前状态',
    to_status VARCHAR(64) NULL COMMENT '变更后状态',
    operator VARCHAR(128) NULL COMMENT '操作人或系统',
    message VARCHAR(1024) NULL COMMENT '事件说明',
    payload_json JSON NULL COMMENT '安全事件载荷',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    KEY idx_adapter_workflow_event_workflow_id (workflow_id),
    KEY idx_adapter_workflow_event_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter交付工作流事件表';
