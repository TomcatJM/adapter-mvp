from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from typing import Any, Iterator


_schema_lock = Lock()
_schema_ready = False


class WorkflowLookupAmbiguousError(ValueError):
    """WorkflowLookupAmbiguousError 异常类型。"""
    pass


def configured() -> bool:
    """判断当前配置是否已就绪。"""
    return all(
        os.getenv(name)
        for name in ["ADAPTER_DB_HOST", "ADAPTER_DB_NAME", "ADAPTER_DB_USER", "ADAPTER_DB_PASSWORD"]
    )


@contextmanager
def connect() -> Iterator[Any]:
    """建立连接。"""
    import pymysql

    conn = pymysql.connect(
        host=os.environ["ADAPTER_DB_HOST"],
        port=int(os.getenv("ADAPTER_DB_PORT", "3306")),
        user=os.environ["ADAPTER_DB_USER"],
        password=os.environ["ADAPTER_DB_PASSWORD"],
        database=os.environ["ADAPTER_DB_NAME"],
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema() -> None:
    """ensure结构。"""
    global _schema_ready
    if _schema_ready or not configured():
        return
    with _schema_lock:
        if _schema_ready:
            return
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_status (
                        task_id VARCHAR(128) PRIMARY KEY COMMENT '任务ID',
                        status VARCHAR(64) NOT NULL COMMENT '任务状态：SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知',
                        message VARCHAR(1024) NOT NULL COMMENT '状态说明',
                        data_json JSON NULL COMMENT '安全结果数据JSON',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter任务状态表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter审计日志表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_api_client (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        client_id VARCHAR(128) NOT NULL COMMENT '调用方ID，例如 codex、yunxiao-flow',
                        client_name VARCHAR(128) NOT NULL COMMENT '调用方名称',
                        token_hash CHAR(64) NOT NULL COMMENT 'API Token SHA-256哈希，禁止存明文',
                        token_plaintext TEXT NULL COMMENT 'API Token原始明文，按用户要求保存，禁止打印到日志',
                        scopes TEXT NULL COMMENT '权限范围，逗号分隔，例如 workflow:read,workflow:write',
                        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0停用',
                        expires_at TIMESTAMP NULL COMMENT '过期时间，空表示不过期',
                        last_used_at TIMESTAMP NULL COMMENT '最近使用时间',
                        created_by VARCHAR(128) NULL COMMENT '创建人',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_api_client_id (client_id),
                        UNIQUE KEY uk_adapter_api_client_token_hash (token_hash),
                        KEY idx_adapter_api_client_enabled (enabled),
                        KEY idx_adapter_api_client_expires_at (expires_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter API调用方Token表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_apifox_project_config (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
                        apifox_project_id VARCHAR(64) NOT NULL COMMENT 'Apifox项目ID',
                        openapi_url VARCHAR(2048) NULL COMMENT '项目专属OpenAPI地址',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_apifox_project_name (project_name),
                        KEY idx_adapter_apifox_project_id (apifox_project_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox项目映射配置表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_apifox_pipeline_config (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        pipeline_id VARCHAR(64) NOT NULL COMMENT '云效流水线ID',
                        project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order',
                        apifox_project_config_id BIGINT NULL COMMENT 'Apifox项目配置主键ID，关联adapter_apifox_project_config.id',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_apifox_pipeline_id (pipeline_id),
                        KEY idx_adapter_apifox_pipeline_project_config_id (apifox_project_config_id),
                        KEY idx_adapter_apifox_pipeline_project_name (project_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter Apifox流水线项目映射配置表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_yunxiao_account_config (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        account_name VARCHAR(128) NOT NULL COMMENT '账号配置名称，例如 default',
                        auth_type VARCHAR(32) NOT NULL DEFAULT 'acs_ak' COMMENT '鉴权类型：acs_ak阿里云AK签名，legacy_token旧云效Token',
                        access_key_id VARCHAR(256) NULL COMMENT '阿里云AccessKey ID，acs_ak必填',
                        access_key_secret VARCHAR(1024) NULL COMMENT '阿里云AccessKey Secret，acs_ak必填',
                        legacy_token TEXT NULL COMMENT '旧云效Token，legacy_token必填',
                        security_token TEXT NULL COMMENT '临时安全令牌，可选',
                        endpoint VARCHAR(256) NOT NULL DEFAULT 'devops.cn-hangzhou.aliyuncs.com' COMMENT '云效OpenAPI Endpoint',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_yunxiao_account_name (account_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效账号AK配置表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_yunxiao_project_config (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        project_name VARCHAR(128) NOT NULL COMMENT '业务项目名称，例如 jdb-school-crm',
                        account_name VARCHAR(128) NOT NULL COMMENT '云效账号配置名称，关联adapter_yunxiao_account_config.account_name',
                        account_config_id BIGINT NULL COMMENT '云效账号配置主键ID，关联adapter_yunxiao_account_config.id',
                        organization_id VARCHAR(128) NOT NULL COMMENT '云效企业/组织ID',
                        project_id VARCHAR(128) NOT NULL COMMENT '云效项目ID或spaceIdentifier',
                        sprint_id VARCHAR(128) NULL COMMENT '云效迭代ID，旧接口可选',
                        workitem_category VARCHAR(32) NOT NULL DEFAULT 'Req' COMMENT '云效需求工作项分类，例如 Req',
                        workitem_type_identifier VARCHAR(128) NOT NULL COMMENT '云效需求工作项类型ID',
                        task_workitem_category VARCHAR(32) NULL COMMENT '云效任务工作项分类，例如 Task',
                        task_workitem_type_identifier VARCHAR(128) NULL COMMENT '云效任务工作项类型ID',
                        default_assignee VARCHAR(128) NOT NULL COMMENT '默认负责人云效账号ID',
                        priority_field_id VARCHAR(128) NULL COMMENT '优先级字段ID，可选',
                        priority_default_value VARCHAR(128) NULL COMMENT '默认优先级值，可选',
                        participants TEXT NULL COMMENT '参与人，逗号分隔',
                        trackers TEXT NULL COMMENT '关注人，逗号分隔',
                        verifier VARCHAR(128) NULL COMMENT '验证人云效账号ID',
                        done_status_id VARCHAR(128) NULL COMMENT '云效完成状态ID，用于关单',
                        done_status_field_id VARCHAR(128) NULL COMMENT '云效状态字段ID，默认status',
                        done_status_names VARCHAR(512) NULL COMMENT '已完成状态名称，逗号分隔，用于幂等判断',
                        comment_field_key VARCHAR(128) NULL COMMENT '回写字段Key，保留扩展',
                        comment_format_type VARCHAR(32) NULL COMMENT '评论格式，默认MARKDOWN',
                        close_transition_id VARCHAR(128) NULL COMMENT '云效关闭流转ID，优先于done_status_id',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_yunxiao_project_name (project_name),
                        KEY idx_adapter_yunxiao_project_account_config_id (account_config_id),
                        KEY idx_adapter_yunxiao_project_account_name (account_name),
                        KEY idx_adapter_yunxiao_project_id (project_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效项目映射配置表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_yunxiao_member (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        member_name VARCHAR(128) NOT NULL COMMENT '人员姓名，例如 姬志猛',
                        yunxiao_account_id VARCHAR(128) NOT NULL COMMENT '云效账号ID',
                        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0停用',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_yunxiao_member_account (yunxiao_account_id),
                        KEY idx_adapter_yunxiao_member_name (member_name),
                        KEY idx_adapter_yunxiao_member_enabled (enabled)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效人员表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_yunxiao_project_member_relation (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        project_name VARCHAR(128) NOT NULL COMMENT '业务项目名称，例如 jdb-school-crm',
                        project_config_id BIGINT NULL COMMENT '云效项目配置主键ID，关联adapter_yunxiao_project_config.id',
                        yunxiao_account_id VARCHAR(128) NOT NULL COMMENT '云效账号ID，关联adapter_yunxiao_member.yunxiao_account_id',
                        member_id BIGINT NULL COMMENT '云效人员主键ID，关联adapter_yunxiao_member.id',
                        is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否项目默认负责人：1是，0否',
                        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0停用',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_yunxiao_project_member_relation (project_name, yunxiao_account_id),
                        KEY idx_adapter_yunxiao_project_member_relation_project_id (project_config_id),
                        KEY idx_adapter_yunxiao_project_member_relation_member_id (member_id),
                        KEY idx_adapter_yunxiao_project_member_relation_default (project_name, is_default, enabled),
                        KEY idx_adapter_yunxiao_project_member_relation_account (yunxiao_account_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效项目人员关联表'
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS adapter_yunxiao_project_member (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '自增主键',
                        project_name VARCHAR(128) NOT NULL COMMENT '业务项目名称，例如 jdb-school-crm',
                        member_name VARCHAR(128) NOT NULL COMMENT '负责人姓名，例如 姬志猛',
                        yunxiao_account_id VARCHAR(128) NOT NULL COMMENT '云效账号ID',
                        is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认负责人：1是，0否',
                        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0停用',
                        remark VARCHAR(512) NULL COMMENT '备注',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_adapter_yunxiao_project_member_name (project_name, member_name),
                        UNIQUE KEY uk_adapter_yunxiao_project_member_account (project_name, yunxiao_account_id),
                        KEY idx_adapter_yunxiao_project_member_default (project_name, is_default, enabled)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter云效项目人员配置表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉应用配置表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉应用表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter钉钉文档读取配置表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter交付工作流实例表'
                    """
                )
                cursor.execute(
                    """
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
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Adapter交付工作流事件表'
                    """
                )
                _ensure_comments(cursor)
                _migrate_yunxiao_project_members(cursor)
                _migrate_dingtalk_app_config(cursor)
                _backfill_config_relation_ids(cursor)
        _schema_ready = True


def _ensure_comments(cursor) -> None:
    """内部辅助函数：ensurecomments。"""
    statements = [
        "ALTER TABLE adapter_status COMMENT='Adapter任务状态表'",
        "ALTER TABLE adapter_status MODIFY task_id VARCHAR(128) COMMENT '任务ID'",
        "ALTER TABLE adapter_status MODIFY status VARCHAR(64) NOT NULL COMMENT '任务状态：SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知'",
        "ALTER TABLE adapter_status MODIFY message VARCHAR(1024) NOT NULL COMMENT '状态说明'",
        "ALTER TABLE adapter_status MODIFY data_json JSON NULL COMMENT '安全结果数据JSON'",
        "ALTER TABLE adapter_status MODIFY updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'",
        "ALTER TABLE adapter_audit COMMENT='Adapter审计日志表'",
        "ALTER TABLE adapter_audit MODIFY id BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键'",
        "ALTER TABLE adapter_audit MODIFY ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件时间'",
        "ALTER TABLE adapter_audit MODIFY event VARCHAR(64) NOT NULL COMMENT '事件类型：preview预览，execute执行，status状态查询'",
        "ALTER TABLE adapter_audit MODIFY task_id VARCHAR(128) NULL COMMENT '任务ID'",
        "ALTER TABLE adapter_audit MODIFY operator VARCHAR(128) NULL COMMENT '操作人'",
        "ALTER TABLE adapter_audit MODIFY system_name VARCHAR(64) NULL COMMENT '适配系统'",
        "ALTER TABLE adapter_audit MODIFY action_name VARCHAR(128) NULL COMMENT '适配动作'",
        "ALTER TABLE adapter_audit MODIFY env_name VARCHAR(64) NULL COMMENT '环境'",
        "ALTER TABLE adapter_audit MODIFY host_id VARCHAR(128) NULL COMMENT '主机ID'",
        "ALTER TABLE adapter_audit MODIFY approval_id VARCHAR(128) NULL COMMENT '审批ID'",
        "ALTER TABLE adapter_audit MODIFY approved TINYINT(1) NULL COMMENT '是否显式审批：1是，0否'",
        "ALTER TABLE adapter_audit MODIFY status VARCHAR(64) NULL COMMENT '执行状态：PREVIEWED已预览，BLOCKED已阻断，SUCCESS成功，FAILED失败，WAIT_APPROVAL待审批，UNKNOWN未知'",
        "ALTER TABLE adapter_audit MODIFY message VARCHAR(1024) NULL COMMENT '执行说明'",
        "ALTER TABLE adapter_audit MODIFY elapsed_ms INT NULL COMMENT '耗时毫秒'",
        "ALTER TABLE adapter_audit MODIFY payload_json JSON NULL COMMENT '安全审计载荷JSON'",
        "ALTER TABLE adapter_api_client COMMENT='Adapter API调用方Token表'",
        "ALTER TABLE adapter_api_client ADD COLUMN token_plaintext TEXT NULL COMMENT 'API Token原始明文，按用户要求保存，禁止打印到日志' AFTER token_hash",
        "ALTER TABLE adapter_api_client MODIFY token_plaintext TEXT NULL COMMENT 'API Token原始明文，按用户要求保存，禁止打印到日志'",
        "ALTER TABLE adapter_api_client DROP COLUMN token_ciphertext",
        "ALTER TABLE adapter_api_client DROP COLUMN token_last4",
        "ALTER TABLE adapter_apifox_project_config COMMENT='Adapter Apifox项目映射配置表'",
        "ALTER TABLE adapter_apifox_project_config MODIFY id BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键'",
        "ALTER TABLE adapter_apifox_project_config MODIFY project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order'",
        "ALTER TABLE adapter_apifox_project_config MODIFY apifox_project_id VARCHAR(64) NOT NULL COMMENT 'Apifox项目ID'",
        "ALTER TABLE adapter_apifox_project_config ADD COLUMN openapi_url VARCHAR(2048) NULL COMMENT '项目专属OpenAPI地址' AFTER apifox_project_id",
        "ALTER TABLE adapter_apifox_project_config MODIFY openapi_url VARCHAR(2048) NULL COMMENT '项目专属OpenAPI地址'",
        "ALTER TABLE adapter_apifox_project_config MODIFY remark VARCHAR(512) NULL COMMENT '备注'",
        "ALTER TABLE adapter_apifox_project_config MODIFY created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
        "ALTER TABLE adapter_apifox_project_config MODIFY updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'",
        "ALTER TABLE adapter_apifox_pipeline_config COMMENT='Adapter Apifox流水线项目映射配置表'",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY id BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键'",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY pipeline_id VARCHAR(64) NOT NULL COMMENT '云效流水线ID'",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY project_name VARCHAR(128) NOT NULL COMMENT '项目名称，例如 jdb-order'",
        "ALTER TABLE adapter_apifox_pipeline_config ADD COLUMN apifox_project_config_id BIGINT NULL COMMENT 'Apifox项目配置主键ID，关联adapter_apifox_project_config.id' AFTER project_name",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY apifox_project_config_id BIGINT NULL COMMENT 'Apifox项目配置主键ID，关联adapter_apifox_project_config.id'",
        "ALTER TABLE adapter_apifox_pipeline_config ADD INDEX idx_adapter_apifox_pipeline_project_config_id (apifox_project_config_id)",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY remark VARCHAR(512) NULL COMMENT '备注'",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
        "ALTER TABLE adapter_apifox_pipeline_config MODIFY updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'",
        "ALTER TABLE adapter_yunxiao_account_config COMMENT='Adapter云效账号AK配置表'",
        "ALTER TABLE adapter_yunxiao_account_config ADD COLUMN auth_type VARCHAR(32) NOT NULL DEFAULT 'acs_ak' COMMENT '鉴权类型：acs_ak阿里云AK签名，legacy_token旧云效Token' AFTER account_name",
        "ALTER TABLE adapter_yunxiao_account_config MODIFY access_key_id VARCHAR(256) NULL COMMENT '阿里云AccessKey ID，acs_ak必填'",
        "ALTER TABLE adapter_yunxiao_account_config MODIFY access_key_secret VARCHAR(1024) NULL COMMENT '阿里云AccessKey Secret，acs_ak必填'",
        "ALTER TABLE adapter_yunxiao_account_config ADD COLUMN legacy_token TEXT NULL COMMENT '旧云效Token，legacy_token必填' AFTER access_key_secret",
        "ALTER TABLE adapter_yunxiao_project_config COMMENT='Adapter云效项目映射配置表'",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN account_config_id BIGINT NULL COMMENT '云效账号配置主键ID，关联adapter_yunxiao_account_config.id' AFTER account_name",
        "ALTER TABLE adapter_yunxiao_project_config MODIFY account_config_id BIGINT NULL COMMENT '云效账号配置主键ID，关联adapter_yunxiao_account_config.id'",
        "ALTER TABLE adapter_yunxiao_project_config ADD INDEX idx_adapter_yunxiao_project_account_config_id (account_config_id)",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN sprint_id VARCHAR(128) NULL COMMENT '云效迭代ID，旧接口可选' AFTER project_id",
        "ALTER TABLE adapter_yunxiao_project_config MODIFY workitem_category VARCHAR(32) NOT NULL DEFAULT 'Req' COMMENT '云效需求工作项分类，例如 Req'",
        "ALTER TABLE adapter_yunxiao_project_config MODIFY workitem_type_identifier VARCHAR(128) NOT NULL COMMENT '云效需求工作项类型ID'",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN task_workitem_category VARCHAR(32) NULL COMMENT '云效任务工作项分类，例如 Task' AFTER workitem_type_identifier",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN task_workitem_type_identifier VARCHAR(128) NULL COMMENT '云效任务工作项类型ID' AFTER task_workitem_category",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN done_status_id VARCHAR(128) NULL COMMENT '云效完成状态ID，用于关单' AFTER verifier",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN done_status_field_id VARCHAR(128) NULL COMMENT '云效状态字段ID，默认status' AFTER done_status_id",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN done_status_names VARCHAR(512) NULL COMMENT '已完成状态名称，逗号分隔，用于幂等判断' AFTER done_status_field_id",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN comment_field_key VARCHAR(128) NULL COMMENT '回写字段Key，保留扩展' AFTER done_status_names",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN comment_format_type VARCHAR(32) NULL COMMENT '评论格式，默认MARKDOWN' AFTER comment_field_key",
        "ALTER TABLE adapter_yunxiao_project_config ADD COLUMN close_transition_id VARCHAR(128) NULL COMMENT '云效关闭流转ID，优先于done_status_id' AFTER comment_format_type",
        "ALTER TABLE adapter_yunxiao_member COMMENT='Adapter云效人员表'",
        "ALTER TABLE adapter_yunxiao_project_member_relation COMMENT='Adapter云效项目人员关联表'",
        "ALTER TABLE adapter_yunxiao_project_member_relation ADD COLUMN project_config_id BIGINT NULL COMMENT '云效项目配置主键ID，关联adapter_yunxiao_project_config.id' AFTER project_name",
        "ALTER TABLE adapter_yunxiao_project_member_relation MODIFY project_config_id BIGINT NULL COMMENT '云效项目配置主键ID，关联adapter_yunxiao_project_config.id'",
        "ALTER TABLE adapter_yunxiao_project_member_relation ADD COLUMN member_id BIGINT NULL COMMENT '云效人员主键ID，关联adapter_yunxiao_member.id' AFTER yunxiao_account_id",
        "ALTER TABLE adapter_yunxiao_project_member_relation MODIFY member_id BIGINT NULL COMMENT '云效人员主键ID，关联adapter_yunxiao_member.id'",
        "ALTER TABLE adapter_yunxiao_project_member_relation ADD INDEX idx_adapter_yunxiao_project_member_relation_project_id (project_config_id)",
        "ALTER TABLE adapter_yunxiao_project_member_relation ADD INDEX idx_adapter_yunxiao_project_member_relation_member_id (member_id)",
        "ALTER TABLE adapter_yunxiao_project_member COMMENT='Adapter云效项目人员配置表'",
        "ALTER TABLE adapter_dingtalk_app_config COMMENT='Adapter钉钉文档读取旧版混合配置表'",
        "ALTER TABLE adapter_dingtalk_app_config ADD COLUMN operator_id VARCHAR(128) NULL COMMENT '钉钉文档操作人userId' AFTER token_header_name",
        "ALTER TABLE adapter_dingtalk_app COMMENT='Adapter钉钉应用表'",
        "ALTER TABLE adapter_dingtalk_doc_config COMMENT='Adapter钉钉文档读取配置表'",
    ]
    for statement in statements:
        try:
            cursor.execute(statement)
        except Exception:
            pass


def _migrate_yunxiao_project_members(cursor) -> None:
    """内部辅助函数：migrate云效项目members。"""
    try:
        cursor.execute(
            """
            INSERT INTO adapter_yunxiao_member (
                member_name,
                yunxiao_account_id,
                enabled,
                remark,
                created_at,
                updated_at
            )
            SELECT
                MAX(member_name) AS member_name,
                yunxiao_account_id,
                MAX(enabled) AS enabled,
                MAX(remark) AS remark,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at
            FROM adapter_yunxiao_project_member
            WHERE member_name IS NOT NULL
              AND yunxiao_account_id IS NOT NULL
            GROUP BY yunxiao_account_id
            ON DUPLICATE KEY UPDATE
                member_name = VALUES(member_name),
                enabled = VALUES(enabled),
                remark = COALESCE(VALUES(remark), adapter_yunxiao_member.remark)
            """
        )
        cursor.execute(
            """
            INSERT INTO adapter_yunxiao_project_member_relation (
                project_name,
                yunxiao_account_id,
                is_default,
                enabled,
                remark,
                created_at,
                updated_at
            )
            SELECT
                project_name,
                yunxiao_account_id,
                is_default,
                enabled,
                remark,
                created_at,
                updated_at
            FROM adapter_yunxiao_project_member
            WHERE project_name IS NOT NULL
              AND yunxiao_account_id IS NOT NULL
            ON DUPLICATE KEY UPDATE
                is_default = VALUES(is_default),
                enabled = VALUES(enabled),
                remark = COALESCE(VALUES(remark), adapter_yunxiao_project_member_relation.remark)
            """
        )
    except Exception:
        pass


def _backfill_config_relation_ids(cursor) -> None:
    """回填配置表之间的主键关联ID。"""
    statements = [
        """
        UPDATE adapter_yunxiao_project_config project
        JOIN adapter_yunxiao_account_config account
          ON LOWER(account.account_name) = LOWER(project.account_name)
        SET project.account_config_id = account.id
        WHERE project.account_config_id IS NULL
           OR project.account_config_id <> account.id
        """,
        """
        UPDATE adapter_yunxiao_project_member_relation rel
        JOIN adapter_yunxiao_project_config project
          ON LOWER(project.project_name) = LOWER(rel.project_name)
        SET rel.project_config_id = project.id
        WHERE rel.project_config_id IS NULL
           OR rel.project_config_id <> project.id
        """,
        """
        UPDATE adapter_yunxiao_project_member_relation rel
        JOIN adapter_yunxiao_member member
          ON member.yunxiao_account_id = rel.yunxiao_account_id
        SET rel.member_id = member.id
        WHERE rel.member_id IS NULL
           OR rel.member_id <> member.id
        """,
        """
        UPDATE adapter_apifox_pipeline_config pipeline
        JOIN adapter_apifox_project_config project
          ON LOWER(project.project_name) = LOWER(pipeline.project_name)
        SET pipeline.apifox_project_config_id = project.id
        WHERE pipeline.apifox_project_config_id IS NULL
           OR pipeline.apifox_project_config_id <> project.id
        """,
    ]
    for statement in statements:
        try:
            cursor.execute(statement)
        except Exception:
            pass


def _migrate_dingtalk_app_config(cursor) -> None:
    """内部辅助函数：migrate钉钉app配置。"""
    try:
        cursor.execute(
            """
            INSERT INTO adapter_dingtalk_app (
                app_name,
                app_key,
                app_secret,
                auth_endpoint,
                token_header_name,
                access_token,
                token_expires_at,
                remark
            )
            SELECT
                CASE
                    WHEN NULLIF(TRIM(remark), '') IS NOT NULL THEN TRIM(remark)
                    ELSE config_name
                END AS app_name,
                app_key,
                app_secret,
                auth_endpoint,
                token_header_name,
                access_token,
                token_expires_at,
                remark
            FROM adapter_dingtalk_app_config
            WHERE app_key IS NOT NULL
              AND app_secret IS NOT NULL
            ON DUPLICATE KEY UPDATE
                app_key = adapter_dingtalk_app.app_key,
                app_secret = adapter_dingtalk_app.app_secret,
                auth_endpoint = adapter_dingtalk_app.auth_endpoint,
                token_header_name = adapter_dingtalk_app.token_header_name,
                access_token = adapter_dingtalk_app.access_token,
                token_expires_at = adapter_dingtalk_app.token_expires_at,
                remark = adapter_dingtalk_app.remark
            """
        )
        cursor.execute(
            """
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
            SELECT
                config_name,
                CASE
                    WHEN NULLIF(TRIM(remark), '') IS NOT NULL THEN TRIM(remark)
                    ELSE config_name
                END AS app_name,
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
            FROM adapter_dingtalk_app_config
            WHERE config_name IS NOT NULL
            ON DUPLICATE KEY UPDATE
                app_name = adapter_dingtalk_doc_config.app_name,
                operator_id = adapter_dingtalk_doc_config.operator_id,
                doc_info_method = adapter_dingtalk_doc_config.doc_info_method,
                doc_info_url_template = adapter_dingtalk_doc_config.doc_info_url_template,
                doc_info_body_template = adapter_dingtalk_doc_config.doc_info_body_template,
                doc_read_method = adapter_dingtalk_doc_config.doc_read_method,
                doc_read_url_template = adapter_dingtalk_doc_config.doc_read_url_template,
                doc_read_body_template = adapter_dingtalk_doc_config.doc_read_body_template,
                sheet_list_method = adapter_dingtalk_doc_config.sheet_list_method,
                sheet_list_url_template = adapter_dingtalk_doc_config.sheet_list_url_template,
                sheet_list_body_template = adapter_dingtalk_doc_config.sheet_list_body_template,
                sheet_range_method = adapter_dingtalk_doc_config.sheet_range_method,
                sheet_range_url_template = adapter_dingtalk_doc_config.sheet_range_url_template,
                sheet_range_body_template = adapter_dingtalk_doc_config.sheet_range_body_template,
                remark = adapter_dingtalk_doc_config.remark
            """
        )
    except Exception:
        pass


def dumps(value: Any) -> str:
    """dumps。"""
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def hash_api_token(token: str) -> str:
    """计算 Adapter API token 的存储哈希。"""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def find_api_client_by_token(token: str) -> dict[str, Any] | None:
    """按明文 token 查找启用的 Adapter API 调用方。"""
    token_text = str(token or "").strip()
    if not token_text or not configured():
        return None
    ensure_schema()
    token_hash = hash_api_token(token_text)
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    client_id,
                    client_name,
                    scopes,
                    created_by,
                    remark
                FROM adapter_api_client
                WHERE token_hash = %s
                  AND enabled = 1
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                LIMIT 1
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                """
                UPDATE adapter_api_client
                SET last_used_at = CURRENT_TIMESTAMP
                WHERE client_id = %s
                """,
                (row["client_id"],),
            )
    return {
        "clientId": row.get("client_id"),
        "clientName": row.get("client_name"),
        "scopes": _split_scopes(row.get("scopes")),
        "createdBy": row.get("created_by"),
        "remark": row.get("remark"),
    }


def _split_scopes(value: Any) -> list[str]:
    """拆分 API 调用方权限范围。"""
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def create_workflow_instance(
    *,
    workflow_id: str,
    requirement_key: str | None,
    dingtalk_url: str,
    dingtalk_node_id: str | None,
    repo_url: str | None,
    branch_name: str | None,
    context: dict[str, Any],
    created_by: str | None,
) -> dict[str, Any]:
    """创建工作流instance。"""
    _require_configured()
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO adapter_workflow_instance (
                    workflow_id,
                    requirement_key,
                    dingtalk_url,
                    dingtalk_node_id,
                    repo_url,
                    branch_name,
                    status,
                    context_json,
                    created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'CREATED', %s, %s)
                """,
                (
                    workflow_id,
                    requirement_key,
                    dingtalk_url,
                    dingtalk_node_id,
                    repo_url,
                    branch_name,
                    dumps(context),
                    created_by,
                ),
            )
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type="workflow_started",
                from_status=None,
                to_status="CREATED",
                operator=created_by,
                message="Workflow started",
                payload={"requirementKey": requirement_key, "dingtalkNodeId": dingtalk_node_id},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise RuntimeError(f"Workflow was not created: {workflow_id}")
    return workflow


def find_workflow_instance(workflow_id: str) -> dict[str, Any] | None:
    """查找工作流instance。"""
    _require_configured()
    ensure_schema()
    return _find_workflow_instance_by_clause("workflow_id = %s", (workflow_id,))


def find_workflow_by_yunxiao_task_id(yunxiao_task_id: str) -> dict[str, Any] | None:
    """查找工作流by云效任务ID。"""
    _require_configured()
    ensure_schema()
    if not yunxiao_task_id:
        return None
    return _find_workflow_instance_by_clause("yunxiao_task_id = %s", (yunxiao_task_id,))


def find_workflow_by_pipeline_build(pipeline_id: str, build_number: str) -> dict[str, Any] | None:
    """查找工作流by流水线构建。"""
    _require_configured()
    ensure_schema()
    if not pipeline_id or not build_number:
        return None
    return _find_workflow_instance_by_clause(
        "yunxiao_pipeline_id = %s AND yunxiao_build_number = %s",
        (pipeline_id, build_number),
    )


def find_workflow_by_branch_commit(branch_name: str, commit_id: str) -> dict[str, Any] | None:
    """查找工作流by分支commit。"""
    _require_configured()
    ensure_schema()
    if not branch_name or not commit_id:
        return None
    return _find_workflow_instance_by_clause(
        "branch_name = %s AND commit_id = %s",
        (branch_name, commit_id),
    )


def list_workflows_by_statuses(statuses: list[str] | tuple[str, ...] | set[str], limit: int = 50) -> list[dict[str, Any]]:
    """列出workflowsbystatuses。"""
    _require_configured()
    ensure_schema()
    safe_statuses = [str(status).strip() for status in statuses if str(status or "").strip()]
    if not safe_statuses:
        return []
    safe_limit = max(1, min(int(limit or 50), 200))
    placeholders = ", ".join(["%s"] * len(safe_statuses))
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    workflow_id,
                    requirement_key,
                    dingtalk_url,
                    dingtalk_node_id,
                    yunxiao_task_id,
                    yunxiao_pipeline_id,
                    yunxiao_build_number,
                    repo_url,
                    branch_name,
                    commit_id,
                    apifox_project_id,
                    status,
                    retry_count,
                    last_error,
                    context_json,
                    created_by,
                    created_at,
                    updated_at
                FROM adapter_workflow_instance
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                tuple(safe_statuses + [safe_limit]),
            )
            rows = cursor.fetchall()
    return [_map_workflow_instance(row) for row in rows]


def _find_workflow_instance_by_clause(where_clause: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    """内部辅助函数：查找工作流instancebyclause。"""
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    workflow_id,
                    requirement_key,
                    dingtalk_url,
                    dingtalk_node_id,
                    yunxiao_task_id,
                    yunxiao_pipeline_id,
                    yunxiao_build_number,
                    repo_url,
                    branch_name,
                    commit_id,
                    apifox_project_id,
                    status,
                    retry_count,
                    last_error,
                    context_json,
                    created_by,
                    created_at,
                    updated_at
                FROM adapter_workflow_instance
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT 2
                """,
                params,
            )
            rows = cursor.fetchall()
    if len(rows) > 1:
        raise WorkflowLookupAmbiguousError(f"Multiple workflow instances matched: {where_clause}")
    return _map_workflow_instance(rows[0]) if rows else None


def list_workflow_events(workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """列出工作流events。"""
    _require_configured()
    ensure_schema()
    safe_limit = max(1, min(int(limit or 50), 200))
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    workflow_id,
                    event_type,
                    from_status,
                    to_status,
                    operator,
                    message,
                    payload_json,
                    created_at
                FROM adapter_workflow_event
                WHERE workflow_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (workflow_id, safe_limit),
            )
            rows = cursor.fetchall()
    return [_map_workflow_event(row) for row in rows]


def update_workflow_doc_read(
    *,
    workflow_id: str,
    from_status: str,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流文档读取。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status=from_status,
        to_status="DOC_READ",
        context=context,
        operator=operator,
        event_type="doc_read",
        message="DingTalk document read",
        event_payload=event_payload,
        clear_error=True,
    )


def update_workflow_requirement(
    *,
    workflow_id: str,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流requirement。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status="DOC_READ",
        to_status="REQUIREMENT_PARSED",
        context=context,
        operator=operator,
        event_type="requirement_parsed",
        message="Requirement parsed",
        event_payload=event_payload,
        clear_error=True,
    )


def update_workflow_coding_result(
    *,
    workflow_id: str,
    from_status: str,
    branch_name: str | None,
    commit_id: str | None,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流编码结果。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status=from_status,
        to_status="CODE_SUBMITTED",
        context=context,
        operator=operator,
        event_type="coding_result_submitted",
        message="Coding result submitted",
        event_payload=event_payload,
        branch_name=branch_name,
        commit_id=commit_id,
        clear_error=True,
    )


def update_workflow_yunxiao_task_created(
    *,
    workflow_id: str,
    from_status: str,
    yunxiao_task_id: str,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流云效任务已创建。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status=from_status,
        to_status="YUNXIAO_TASK_CREATED",
        context=context,
        operator=operator,
        event_type="yunxiao_workitem_created",
        message="Yunxiao workitem created",
        event_payload=event_payload,
        yunxiao_task_id=yunxiao_task_id,
        clear_error=True,
    )


def update_workflow_coding_requested(
    *,
    workflow_id: str,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流编码requested。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status="YUNXIAO_TASK_CREATED",
        to_status="CODING_REQUESTED",
        context=context,
        operator=operator,
        event_type="coding_requested",
        message="Coding requested",
        event_payload=event_payload,
        clear_error=True,
    )


def update_workflow_pipeline_running(
    *,
    workflow_id: str,
    pipeline_id: str | None,
    build_number: str | None,
    branch_name: str | None,
    commit_id: str | None,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流流水线running。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status="CODE_SUBMITTED",
        to_status="PIPELINE_RUNNING",
        context=context,
        operator=operator,
        event_type="pipeline_running",
        message="Yunxiao pipeline running",
        event_payload=event_payload,
        branch_name=branch_name,
        commit_id=commit_id,
        yunxiao_pipeline_id=pipeline_id,
        yunxiao_build_number=build_number,
        clear_error=True,
    )


def update_workflow_pipeline_success(
    *,
    workflow_id: str,
    from_status: str,
    pipeline_id: str | None,
    build_number: str | None,
    branch_name: str | None,
    commit_id: str | None,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流流水线success。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status=from_status,
        to_status="PIPELINE_SUCCESS",
        context=context,
        operator=operator,
        event_type="pipeline_success",
        message="Yunxiao pipeline succeeded",
        event_payload=event_payload,
        branch_name=branch_name,
        commit_id=commit_id,
        yunxiao_pipeline_id=pipeline_id,
        yunxiao_build_number=build_number,
        clear_error=True,
    )


def update_workflow_pipeline_failed(
    *,
    workflow_id: str,
    from_status: str,
    pipeline_id: str | None,
    build_number: str | None,
    branch_name: str | None,
    commit_id: str | None,
    context: dict[str, Any],
    operator: str | None,
    error: str,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流流水线failed。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status=from_status,
        to_status="PIPELINE_FAILED",
        context=context,
        operator=operator,
        event_type="pipeline_failed",
        message=str(error or "Yunxiao pipeline failed")[:1024],
        event_payload=event_payload,
        branch_name=branch_name,
        commit_id=commit_id,
        yunxiao_pipeline_id=pipeline_id,
        yunxiao_build_number=build_number,
        last_error=str(error or "Yunxiao pipeline failed")[:2048],
    )


def update_workflow_apifox_synced(
    *,
    workflow_id: str,
    context: dict[str, Any],
    apifox_project_id: str | None,
    operator: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """更新工作流Apifoxsynced。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status="PIPELINE_SUCCESS",
        to_status="APIFOX_SYNCED",
        context=context,
        operator=operator,
        event_type="apifox_synced",
        message="Apifox OpenAPI synced",
        event_payload=event_payload,
        apifox_project_id=apifox_project_id,
        clear_error=True,
    )


def update_workflow_yunxiao_task_closed(
    *,
    workflow_id: str,
    context: dict[str, Any],
    operator: str | None,
    event_payload: dict[str, Any],
    event_type: str = "yunxiao_workitem_closed",
    message: str = "Yunxiao workitem closed",
) -> dict[str, Any]:
    """更新工作流云效任务已关闭。"""
    return _update_workflow_state(
        workflow_id=workflow_id,
        expected_status="APIFOX_SYNCED",
        to_status="YUNXIAO_TASK_CLOSED",
        context=context,
        operator=operator,
        event_type=event_type,
        message=message,
        event_payload=event_payload,
        clear_error=True,
    )


def record_workflow_apifox_result(
    *,
    workflow_id: str,
    status: str,
    context: dict[str, Any],
    operator: str | None,
    event_type: str,
    message: str,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """记录工作流Apifox结果。"""
    _require_configured()
    ensure_schema()
    clipped_message = str(message or "")[:1024]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET context_json = %s,
                    last_error = %s
                WHERE workflow_id = %s
                  AND status = %s
                """,
                (dumps(context), clipped_message, workflow_id, status),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not {status}: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type=event_type,
                from_status=status,
                to_status=status,
                operator=operator,
                message=clipped_message,
                payload=event_payload,
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def record_workflow_context_event(
    *,
    workflow_id: str,
    status: str,
    context: dict[str, Any],
    operator: str | None,
    event_type: str,
    message: str,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """记录工作流上下文事件，不改变当前状态。"""
    _require_configured()
    ensure_schema()
    clipped_message = str(message or "")[:1024]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET context_json = %s
                WHERE workflow_id = %s
                  AND status = %s
                """,
                (dumps(context), workflow_id, status),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not {status}: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type=event_type,
                from_status=status,
                to_status=status,
                operator=operator,
                message=clipped_message,
                payload=event_payload,
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def mark_workflow_needs_human(
    *,
    workflow_id: str,
    from_status: str,
    error: str,
    operator: str | None,
    event_type: str,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """标记工作流needs人工。"""
    _require_configured()
    ensure_schema()
    clipped_error = str(error or "")[:2048]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET status = 'NEEDS_HUMAN',
                    last_error = %s,
                    retry_count = retry_count + 1
                WHERE workflow_id = %s
                  AND status = %s
                """,
                (clipped_error, workflow_id, from_status),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status changed before NEEDS_HUMAN mark: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type=event_type,
                from_status=from_status,
                to_status="NEEDS_HUMAN",
                operator=operator,
                message=clipped_error[:1024],
                payload=event_payload or {},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def resolve_workflow_needs_human(
    *,
    workflow_id: str,
    target_status: str,
    operator: str | None,
    reason: str | None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """解析工作流needs人工。"""
    _require_configured()
    ensure_schema()
    clipped_reason = str(reason or "Workflow manually resolved")[:1024]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET status = %s,
                    last_error = NULL
                WHERE workflow_id = %s
                  AND status = 'NEEDS_HUMAN'
                """,
                (target_status, workflow_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not NEEDS_HUMAN: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type="workflow_resolved",
                from_status="NEEDS_HUMAN",
                to_status=target_status,
                operator=operator,
                message=clipped_reason,
                payload=event_payload or {},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def retry_workflow_from_pipeline_failed(
    *,
    workflow_id: str,
    target_status: str,
    operator: str | None,
    reason: str | None,
    max_retry_count: int,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """重试工作流来自流水线failed。"""
    _require_configured()
    ensure_schema()
    clipped_reason = str(reason or "Workflow retry requested")[:1024]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, retry_count
                FROM adapter_workflow_instance
                WHERE workflow_id = %s
                FOR UPDATE
                """,
                (workflow_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Workflow not found: {workflow_id}")
            current_status = str(row.get("status") or "")
            if current_status != "PIPELINE_FAILED":
                raise ValueError(f"Workflow status is not PIPELINE_FAILED: {workflow_id}")
            retry_count = int(row.get("retry_count") or 0)
            if retry_count >= max_retry_count:
                raise ValueError(
                    f"Workflow retry count exceeded limit: {workflow_id} ({retry_count}/{max_retry_count})"
                )
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET status = %s,
                    last_error = NULL,
                    retry_count = retry_count + 1
                WHERE workflow_id = %s
                  AND status = 'PIPELINE_FAILED'
                """,
                (target_status, workflow_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not PIPELINE_FAILED: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type="workflow_retried",
                from_status="PIPELINE_FAILED",
                to_status=target_status,
                operator=operator,
                message=clipped_reason,
                payload=event_payload or {},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def mark_workflow_failed(
    *,
    workflow_id: str,
    from_status: str,
    error: str,
    operator: str | None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """标记工作流failed。"""
    _require_configured()
    ensure_schema()
    clipped_error = str(error or "")[:2048]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET status = 'FAILED',
                    last_error = %s,
                    retry_count = retry_count + 1
                WHERE workflow_id = %s
                  AND status = %s
                """,
                (clipped_error, workflow_id, from_status),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status changed before failure mark: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type="workflow_failed",
                from_status=from_status,
                to_status="FAILED",
                operator=operator,
                message=clipped_error[:1024],
                payload=event_payload or {},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def record_workflow_error(
    *,
    workflow_id: str,
    status: str,
    error: str,
    operator: str | None,
    event_type: str,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """记录工作流错误。"""
    _require_configured()
    ensure_schema()
    clipped_error = str(error or "")[:2048]
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE adapter_workflow_instance
                SET last_error = %s,
                    retry_count = retry_count + 1
                WHERE workflow_id = %s
                  AND status = %s
                """,
                (clipped_error, workflow_id, status),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not {status}: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type=event_type,
                from_status=status,
                to_status=status,
                operator=operator,
                message=clipped_error[:1024],
                payload=event_payload or {},
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def find_apifox_project_config(project_name: str) -> dict[str, Any] | None:
    """查找Apifox项目配置。"""
    if not configured() or not project_name:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_name, apifox_project_id, openapi_url, remark
                    FROM adapter_apifox_project_config
                    WHERE LOWER(project_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (project_name,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "projectName": row.get("project_name"),
            "apifoxProjectConfigId": row.get("id"),
            "apifoxProjectId": row.get("apifox_project_id"),
            "openapiUrl": row.get("openapi_url"),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def find_apifox_pipeline_config(pipeline_id: str) -> dict[str, Any] | None:
    """查找Apifox流水线配置。"""
    if not configured() or not pipeline_id:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pipeline_id, project_name, apifox_project_config_id, remark
                    FROM adapter_apifox_pipeline_config
                    WHERE pipeline_id = %s
                    LIMIT 1
                    """,
                    (pipeline_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "pipelineId": row.get("pipeline_id"),
            "projectName": row.get("project_name"),
            "apifoxProjectConfigId": row.get("apifox_project_config_id"),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def list_apifox_project_configs() -> list[dict[str, Any]]:
    """列出Apifox项目configs。"""
    if not configured():
        return []
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_name, apifox_project_id, openapi_url, remark
                    FROM adapter_apifox_project_config
                    ORDER BY project_name
                    """
                )
                rows = cursor.fetchall()
        return [
            {
                "projectName": row.get("project_name"),
                "apifoxProjectConfigId": row.get("id"),
                "apifoxProjectId": row.get("apifox_project_id"),
                "openapiUrl": row.get("openapi_url"),
                "remark": row.get("remark"),
            }
            for row in rows
        ]
    except Exception:
        return []


def upsert_apifox_pipeline_config(pipeline_id: str, project_name: str, remark: str | None = None) -> None:
    """upsertApifox流水线配置。"""
    if not configured() or not pipeline_id or not project_name:
        return
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cursor:
            apifox_project_config_id = _find_id_by_name(
                cursor,
                table="adapter_apifox_project_config",
                name_column="project_name",
                name_value=project_name,
            )
            cursor.execute(
                """
                INSERT INTO adapter_apifox_pipeline_config (
                    pipeline_id,
                    project_name,
                    apifox_project_config_id,
                    remark
                )
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    project_name = VALUES(project_name),
                    apifox_project_config_id = VALUES(apifox_project_config_id),
                    remark = VALUES(remark)
                """,
                (pipeline_id, project_name, apifox_project_config_id, remark),
            )


def _find_id_by_name(cursor, *, table: str, name_column: str, name_value: str | None) -> int | None:
    """按唯一业务名称查找配置表主键。"""
    if not name_value:
        return None
    if table not in {
        "adapter_apifox_project_config",
        "adapter_yunxiao_account_config",
        "adapter_yunxiao_project_config",
        "adapter_yunxiao_member",
    }:
        raise ValueError(f"Unsupported table for id lookup: {table}")
    if name_column not in {"project_name", "account_name", "yunxiao_account_id"}:
        raise ValueError(f"Unsupported column for id lookup: {name_column}")
    cursor.execute(
        f"""
        SELECT id
        FROM {table}
        WHERE LOWER({name_column}) = LOWER(%s)
        LIMIT 1
        """,
        (name_value,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row.get("id")


def find_yunxiao_account_config(account_name: str) -> dict[str, Any] | None:
    """查找云效account配置。"""
    if not configured() or not account_name:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        account_name,
                        auth_type,
                        access_key_id,
                        access_key_secret,
                        legacy_token,
                        security_token,
                        endpoint,
                        remark
                    FROM adapter_yunxiao_account_config
                    WHERE LOWER(account_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (account_name,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "accountName": row.get("account_name"),
            "authType": row.get("auth_type") or "acs_ak",
            "accessKeyId": row.get("access_key_id"),
            "accessKeySecret": row.get("access_key_secret"),
            "legacyToken": row.get("legacy_token"),
            "securityToken": row.get("security_token"),
            "endpoint": row.get("endpoint"),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def list_yunxiao_project_configs() -> list[dict[str, Any]]:
    """列出云效项目configs。"""
    if not configured():
        return []
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, project_name, account_config_id, account_name, organization_id, project_id, remark
                    FROM adapter_yunxiao_project_config
                    ORDER BY project_name
                    """
                )
                rows = cursor.fetchall()
        return [
            {
                "projectName": row.get("project_name"),
                "projectConfigId": row.get("id"),
                "accountConfigId": row.get("account_config_id"),
                "accountName": row.get("account_name"),
                "organizationId": row.get("organization_id"),
                "projectId": row.get("project_id"),
                "remark": row.get("remark"),
            }
            for row in rows
        ]
    except Exception:
        return []


def find_yunxiao_project_config(project_name: str) -> dict[str, Any] | None:
    """查找云效项目配置。"""
    if not configured() or not project_name:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_name,
                        id,
                        account_config_id,
                        account_name,
                        organization_id,
                        project_id,
                        sprint_id,
                        workitem_category,
                        workitem_type_identifier,
                        task_workitem_category,
                        task_workitem_type_identifier,
                        default_assignee,
                        priority_field_id,
                        priority_default_value,
                        participants,
                        trackers,
                        verifier,
                        done_status_id,
                        done_status_field_id,
                        done_status_names,
                        comment_field_key,
                        comment_format_type,
                        close_transition_id,
                        remark
                    FROM adapter_yunxiao_project_config
                    WHERE LOWER(project_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (project_name,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "projectName": row.get("project_name"),
            "projectConfigId": row.get("id"),
            "accountConfigId": row.get("account_config_id"),
            "accountName": row.get("account_name"),
            "organizationId": row.get("organization_id"),
            "projectId": row.get("project_id"),
            "sprintId": row.get("sprint_id"),
            "category": row.get("workitem_category"),
            "workitemTypeIdentifier": row.get("workitem_type_identifier"),
            "taskCategory": row.get("task_workitem_category"),
            "taskWorkitemTypeIdentifier": row.get("task_workitem_type_identifier"),
            "assignee": row.get("default_assignee"),
            "priorityFieldId": row.get("priority_field_id"),
            "priorityDefaultValue": row.get("priority_default_value"),
            "participants": row.get("participants"),
            "trackers": row.get("trackers"),
            "verifier": row.get("verifier"),
            "doneStatusId": row.get("done_status_id"),
            "doneStatusFieldId": row.get("done_status_field_id"),
            "doneStatusNames": row.get("done_status_names"),
            "commentFieldKey": row.get("comment_field_key"),
            "commentFormatType": row.get("comment_format_type"),
            "closeTransitionId": row.get("close_transition_id"),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def find_yunxiao_project_member(project_name: str, assignee: str) -> dict[str, Any] | None:
    """查找云效项目成员。"""
    if not configured() or not project_name or not assignee:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        rel.project_name,
                        rel.project_config_id,
                        rel.member_id,
                        member.member_name,
                        member.yunxiao_account_id,
                        rel.is_default,
                        rel.enabled,
                        COALESCE(rel.remark, member.remark) AS remark
                    FROM adapter_yunxiao_project_member_relation rel
                    JOIN adapter_yunxiao_member member
                      ON member.yunxiao_account_id = rel.yunxiao_account_id
                    WHERE LOWER(rel.project_name) = LOWER(%s)
                      AND rel.enabled = 1
                      AND member.enabled = 1
                      AND (
                        LOWER(member.member_name) = LOWER(%s)
                        OR member.yunxiao_account_id = %s
                      )
                    LIMIT 1
                    """,
                    (project_name, assignee, assignee),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        SELECT
                            project_name,
                            member_name,
                            yunxiao_account_id,
                            is_default,
                            enabled,
                            remark
                        FROM adapter_yunxiao_project_member
                        WHERE LOWER(project_name) = LOWER(%s)
                          AND enabled = 1
                          AND (
                            LOWER(member_name) = LOWER(%s)
                            OR yunxiao_account_id = %s
                          )
                        LIMIT 1
                        """,
                        (project_name, assignee, assignee),
                    )
                    row = cursor.fetchone()
        if not row:
            return None
        return {
            "projectName": row.get("project_name"),
            "projectConfigId": row.get("project_config_id"),
            "memberId": row.get("member_id"),
            "name": row.get("member_name"),
            "accountId": row.get("yunxiao_account_id"),
            "isDefault": bool(row.get("is_default")),
            "enabled": bool(row.get("enabled")),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def find_default_yunxiao_project_member(project_name: str) -> dict[str, Any] | None:
    """查找default云效项目成员。"""
    if not configured() or not project_name:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        rel.project_name,
                        rel.project_config_id,
                        rel.member_id,
                        member.member_name,
                        member.yunxiao_account_id,
                        rel.is_default,
                        rel.enabled,
                        COALESCE(rel.remark, member.remark) AS remark
                    FROM adapter_yunxiao_project_member_relation rel
                    JOIN adapter_yunxiao_member member
                      ON member.yunxiao_account_id = rel.yunxiao_account_id
                    WHERE LOWER(rel.project_name) = LOWER(%s)
                      AND rel.enabled = 1
                      AND rel.is_default = 1
                      AND member.enabled = 1
                    ORDER BY rel.updated_at DESC, rel.id DESC
                    LIMIT 1
                    """,
                    (project_name,),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        SELECT
                            project_name,
                            member_name,
                            yunxiao_account_id,
                            is_default,
                            enabled,
                            remark
                        FROM adapter_yunxiao_project_member
                        WHERE LOWER(project_name) = LOWER(%s)
                          AND enabled = 1
                          AND is_default = 1
                        ORDER BY updated_at DESC, id DESC
                        LIMIT 1
                        """,
                        (project_name,),
                    )
                    row = cursor.fetchone()
        if not row:
            return None
        return {
            "projectName": row.get("project_name"),
            "projectConfigId": row.get("project_config_id"),
            "memberId": row.get("member_id"),
            "name": row.get("member_name"),
            "accountId": row.get("yunxiao_account_id"),
            "isDefault": bool(row.get("is_default")),
            "enabled": bool(row.get("enabled")),
            "remark": row.get("remark"),
        }
    except Exception:
        return None


def find_dingtalk_app_config(config_name: str) -> dict[str, Any] | None:
    """查找钉钉app配置。"""
    if not configured() or not config_name:
        return None
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        cfg.config_name,
                        cfg.app_name,
                        app.app_key,
                        app.app_secret,
                        app.auth_endpoint,
                        app.token_header_name,
                        cfg.operator_id,
                        cfg.doc_info_method,
                        cfg.doc_info_url_template,
                        cfg.doc_info_body_template,
                        cfg.doc_read_method,
                        cfg.doc_read_url_template,
                        cfg.doc_read_body_template,
                        cfg.sheet_list_method,
                        cfg.sheet_list_url_template,
                        cfg.sheet_list_body_template,
                        cfg.sheet_range_method,
                        cfg.sheet_range_url_template,
                        cfg.sheet_range_body_template,
                        app.access_token,
                        app.token_expires_at,
                        COALESCE(cfg.remark, app.remark) AS remark
                    FROM adapter_dingtalk_doc_config cfg
                    JOIN adapter_dingtalk_app app
                      ON app.app_name = cfg.app_name
                    WHERE cfg.config_name = %s
                    LIMIT 1
                    """,
                    (config_name,),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        SELECT
                            config_name,
                            NULL AS app_name,
                            app_key,
                            app_secret,
                            auth_endpoint,
                            token_header_name,
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
                            access_token,
                            token_expires_at,
                            remark
                        FROM adapter_dingtalk_app_config
                        WHERE config_name = %s
                        LIMIT 1
                        """,
                        (config_name,),
                    )
                    row = cursor.fetchone()
        if not row:
            return None
        return _map_dingtalk_config(row)
    except Exception:
        return None


def update_dingtalk_token_cache(config_name: str, access_token: str, token_expires_at: datetime) -> None:
    """更新钉钉令牌缓存。"""
    if not configured() or not config_name:
        return
    try:
        ensure_schema()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE adapter_dingtalk_app app
                    JOIN adapter_dingtalk_doc_config cfg
                      ON cfg.app_name = app.app_name
                    SET app.access_token = %s,
                        app.token_expires_at = %s
                    WHERE cfg.config_name = %s
                    """,
                    (access_token, token_expires_at.replace(tzinfo=None), config_name),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        UPDATE adapter_dingtalk_app_config
                        SET access_token = %s,
                            token_expires_at = %s
                        WHERE config_name = %s
                        """,
                        (access_token, token_expires_at.replace(tzinfo=None), config_name),
                    )
    except Exception:
        return


def _update_workflow_state(
    *,
    workflow_id: str,
    expected_status: str,
    to_status: str,
    context: dict[str, Any],
    operator: str | None,
    event_type: str,
    message: str,
    event_payload: dict[str, Any],
    branch_name: str | None = None,
    commit_id: str | None = None,
    yunxiao_task_id: str | None = None,
    yunxiao_pipeline_id: str | None = None,
    yunxiao_build_number: str | None = None,
    apifox_project_id: str | None = None,
    last_error: str | None = None,
    clear_error: bool = False,
) -> dict[str, Any]:
    """内部辅助函数：更新工作流state。"""
    _require_configured()
    ensure_schema()
    assignments = ["status = %s", "context_json = %s"]
    params: list[Any] = [to_status, dumps(context)]
    if branch_name is not None:
        assignments.append("branch_name = %s")
        params.append(branch_name)
    if commit_id is not None:
        assignments.append("commit_id = %s")
        params.append(commit_id)
    if yunxiao_task_id is not None:
        assignments.append("yunxiao_task_id = %s")
        params.append(yunxiao_task_id)
    if yunxiao_pipeline_id is not None:
        assignments.append("yunxiao_pipeline_id = %s")
        params.append(yunxiao_pipeline_id)
    if yunxiao_build_number is not None:
        assignments.append("yunxiao_build_number = %s")
        params.append(yunxiao_build_number)
    if apifox_project_id is not None:
        assignments.append("apifox_project_id = %s")
        params.append(apifox_project_id)
    if last_error is not None:
        assignments.append("last_error = %s")
        params.append(last_error)
    if clear_error:
        assignments.append("last_error = NULL")
    params.extend([workflow_id, expected_status])
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE adapter_workflow_instance
                SET {", ".join(assignments)}
                WHERE workflow_id = %s
                  AND status = %s
                """,
                tuple(params),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Workflow status is not {expected_status}: {workflow_id}")
            _insert_workflow_event(
                cursor,
                workflow_id=workflow_id,
                event_type=event_type,
                from_status=expected_status,
                to_status=to_status,
                operator=operator,
                message=message,
                payload=event_payload,
            )
    workflow = find_workflow_instance(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")
    return workflow


def _insert_workflow_event(
    cursor,
    *,
    workflow_id: str,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    operator: str | None,
    message: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """内部辅助函数：插入工作流事件。"""
    cursor.execute(
        """
        INSERT INTO adapter_workflow_event (
            workflow_id,
            event_type,
            from_status,
            to_status,
            operator,
            message,
            payload_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            workflow_id,
            event_type,
            from_status,
            to_status,
            operator,
            message,
            dumps(payload),
        ),
    )


def _map_workflow_instance(row: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：map工作流instance。"""
    context = _json_or_none(row.get("context_json")) or {}
    return {
        "workflowId": row.get("workflow_id"),
        "requirementKey": row.get("requirement_key"),
        "dingtalkUrl": row.get("dingtalk_url"),
        "dingtalkNodeId": row.get("dingtalk_node_id"),
        "yunxiaoTaskId": row.get("yunxiao_task_id"),
        "yunxiaoTaskDisplayId": _extract_yunxiao_task_display_id(context),
        "yunxiaoPipelineId": row.get("yunxiao_pipeline_id"),
        "yunxiaoBuildNumber": row.get("yunxiao_build_number"),
        "repoUrl": row.get("repo_url"),
        "branchName": row.get("branch_name"),
        "commitId": row.get("commit_id"),
        "apifoxProjectId": row.get("apifox_project_id"),
        "status": row.get("status"),
        "retryCount": row.get("retry_count") or 0,
        "lastError": row.get("last_error"),
        "context": context,
        "createdBy": row.get("created_by"),
        "createdAt": _iso_or_none(row.get("created_at")),
        "updatedAt": _iso_or_none(row.get("updated_at")),
    }


def _extract_yunxiao_task_display_id(context: dict[str, Any]) -> str | None:
    """内部辅助函数：提取云效任务展示ID。"""
    if not isinstance(context, dict):
        return None
    yunxiao = context.get("yunxiao") if isinstance(context.get("yunxiao"), dict) else {}
    for source in (
        yunxiao.get("createResult") if isinstance(yunxiao.get("createResult"), dict) else {},
        yunxiao.get("closeResult") if isinstance(yunxiao.get("closeResult"), dict) else {},
        context.get("codingRequest") if isinstance(context.get("codingRequest"), dict) else {},
    ):
        value = source.get("yunxiaoTaskDisplayId") or source.get("workitemDisplayId")
        if value not in (None, ""):
            return str(value).strip()
    return None


def _map_workflow_event(row: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：map工作流事件。"""
    return {
        "id": row.get("id"),
        "workflowId": row.get("workflow_id"),
        "eventType": row.get("event_type"),
        "fromStatus": row.get("from_status"),
        "toStatus": row.get("to_status"),
        "operator": row.get("operator"),
        "message": row.get("message"),
        "payload": _json_or_none(row.get("payload_json")) or {},
        "createdAt": _iso_or_none(row.get("created_at")),
    }


def upsert_dingtalk_doc_config(config_name: str, changes: dict[str, Any]) -> dict[str, Any]:
    """upsert钉钉文档配置。"""
    if not configured():
        raise RuntimeError("Database env is not configured")
    name = (config_name or "default").strip()
    if not name:
        raise ValueError("DingTalk configName is required")
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
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
                FROM adapter_dingtalk_doc_config
                WHERE config_name = %s
                LIMIT 1
                """,
                (name,),
            )
            current = cursor.fetchone() or {}
            values = _doc_config_values(name, current, changes)
            cursor.execute(
                """
                SELECT app_name
                FROM adapter_dingtalk_app
                WHERE app_name = %s
                LIMIT 1
                """,
                (values["app_name"],),
            )
            if not cursor.fetchone():
                raise ValueError(f"DingTalk app is missing: {values['app_name']}")

            cursor.execute(
                """
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    remark = VALUES(remark)
                """,
                _doc_config_tuple(values),
            )
            cursor.execute(
                """
                UPDATE adapter_dingtalk_app_config
                SET operator_id = %s,
                    doc_info_method = %s,
                    doc_info_url_template = %s,
                    doc_info_body_template = %s,
                    doc_read_method = %s,
                    doc_read_url_template = %s,
                    doc_read_body_template = %s,
                    sheet_list_method = %s,
                    sheet_list_url_template = %s,
                    sheet_list_body_template = %s,
                    sheet_range_method = %s,
                    sheet_range_url_template = %s,
                    sheet_range_body_template = %s,
                    remark = %s
                WHERE config_name = %s
                """,
                (
                    values["operator_id"],
                    values["doc_info_method"],
                    values["doc_info_url_template"],
                    values["doc_info_body_template"],
                    values["doc_read_method"],
                    values["doc_read_url_template"],
                    values["doc_read_body_template"],
                    values["sheet_list_method"],
                    values["sheet_list_url_template"],
                    values["sheet_list_body_template"],
                    values["sheet_range_method"],
                    values["sheet_range_url_template"],
                    values["sheet_range_body_template"],
                    values["remark"] or values["app_name"],
                    name,
                ),
            )
    return _doc_config_summary(values)


def _map_dingtalk_config(row: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：map钉钉配置。"""
    return {
        "configName": row.get("config_name"),
        "appName": row.get("app_name"),
        "appKey": row.get("app_key"),
        "appSecret": row.get("app_secret"),
        "authEndpoint": row.get("auth_endpoint"),
        "tokenHeaderName": row.get("token_header_name"),
        "operatorId": row.get("operator_id"),
        "doc_infoMethod": row.get("doc_info_method"),
        "doc_infoUrlTemplate": row.get("doc_info_url_template"),
        "doc_infoBodyTemplate": _json_or_none(row.get("doc_info_body_template")),
        "doc_readMethod": row.get("doc_read_method"),
        "doc_readUrlTemplate": row.get("doc_read_url_template"),
        "doc_readBodyTemplate": _json_or_none(row.get("doc_read_body_template")),
        "sheet_listMethod": row.get("sheet_list_method"),
        "sheet_listUrlTemplate": row.get("sheet_list_url_template"),
        "sheet_listBodyTemplate": _json_or_none(row.get("sheet_list_body_template")),
        "sheet_rangeMethod": row.get("sheet_range_method"),
        "sheet_rangeUrlTemplate": row.get("sheet_range_url_template"),
        "sheet_rangeBodyTemplate": _json_or_none(row.get("sheet_range_body_template")),
        "accessToken": row.get("access_token"),
        "tokenExpiresAt": row.get("token_expires_at"),
        "remark": row.get("remark"),
    }


def _doc_config_values(config_name: str, current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：文档配置values。"""
    app_name = _changed_value(changes, "app_name", current.get("app_name"))
    if not app_name:
        app_name = os.getenv("DINGTALK_APP_NAME") or "JDB小钉"
    return {
        "config_name": config_name,
        "app_name": str(app_name).strip(),
        "operator_id": _nullable_text(_changed_value(changes, "operator_id", current.get("operator_id"))),
        "doc_info_method": _method_value(changes, current, "doc_info_method"),
        "doc_info_url_template": _nullable_text(
            _changed_value(changes, "doc_info_url_template", current.get("doc_info_url_template"))
        ),
        "doc_info_body_template": _json_text_or_none(
            _changed_value(changes, "doc_info_body_template", current.get("doc_info_body_template"))
        ),
        "doc_read_method": _method_value(changes, current, "doc_read_method"),
        "doc_read_url_template": _nullable_text(
            _changed_value(changes, "doc_read_url_template", current.get("doc_read_url_template"))
        ),
        "doc_read_body_template": _json_text_or_none(
            _changed_value(changes, "doc_read_body_template", current.get("doc_read_body_template"))
        ),
        "sheet_list_method": _method_value(changes, current, "sheet_list_method"),
        "sheet_list_url_template": _nullable_text(
            _changed_value(changes, "sheet_list_url_template", current.get("sheet_list_url_template"))
        ),
        "sheet_list_body_template": _json_text_or_none(
            _changed_value(changes, "sheet_list_body_template", current.get("sheet_list_body_template"))
        ),
        "sheet_range_method": _method_value(changes, current, "sheet_range_method"),
        "sheet_range_url_template": _nullable_text(
            _changed_value(changes, "sheet_range_url_template", current.get("sheet_range_url_template"))
        ),
        "sheet_range_body_template": _json_text_or_none(
            _changed_value(changes, "sheet_range_body_template", current.get("sheet_range_body_template"))
        ),
        "remark": _nullable_text(_changed_value(changes, "remark", current.get("remark"))),
    }


def _changed_value(changes: dict[str, Any], key: str, current: Any) -> Any:
    """内部辅助函数：changed值。"""
    return changes[key] if key in changes else current


def _method_value(changes: dict[str, Any], current: dict[str, Any], key: str) -> str:
    """内部辅助函数：method值。"""
    value = _changed_value(changes, key, current.get(key) or "GET")
    return str(value or "GET").upper()


def _nullable_text(value: Any) -> str | None:
    """内部辅助函数：nullable文本。"""
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _json_text_or_none(value: Any) -> str | None:
    """内部辅助函数：JSON文本ornone。"""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        parsed = _json_or_none(value)
        if isinstance(parsed, str):
            return value
        value = parsed
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _doc_config_tuple(values: dict[str, Any]) -> tuple[Any, ...]:
    """内部辅助函数：文档配置tuple。"""
    return (
        values["config_name"],
        values["app_name"],
        values["operator_id"],
        values["doc_info_method"],
        values["doc_info_url_template"],
        values["doc_info_body_template"],
        values["doc_read_method"],
        values["doc_read_url_template"],
        values["doc_read_body_template"],
        values["sheet_list_method"],
        values["sheet_list_url_template"],
        values["sheet_list_body_template"],
        values["sheet_range_method"],
        values["sheet_range_url_template"],
        values["sheet_range_body_template"],
        values["remark"],
    )


def _doc_config_summary(values: dict[str, Any]) -> dict[str, Any]:
    """内部辅助函数：文档配置摘要。"""
    return {
        "configName": values["config_name"],
        "appName": values["app_name"],
        "operatorIdSet": bool(values.get("operator_id")),
        "operatorIdLength": len(values.get("operator_id") or ""),
        "docInfoConfigured": bool(values.get("doc_info_url_template")),
        "docReadConfigured": bool(values.get("doc_read_url_template")),
        "sheetListConfigured": bool(values.get("sheet_list_url_template")),
        "sheetRangeConfigured": bool(values.get("sheet_range_url_template")),
        "remark": values.get("remark"),
    }


def _json_or_none(value: Any) -> Any:
    """内部辅助函数：JSONornone。"""
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _iso_or_none(value: Any) -> str | None:
    """内部辅助函数：isoornone。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if value in (None, ""):
        return None
    return str(value)


def _require_configured() -> None:
    """内部辅助函数：要求已配置。"""
    if not configured():
        raise RuntimeError("Database env is not configured")
