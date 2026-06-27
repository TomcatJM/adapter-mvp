from typing import Any

from pydantic import BaseModel, Field


class AdapterRequest(BaseModel):
    """AdapterRequest 请求模型。"""
    task_id: str = Field(alias="taskId")
    operator: str
    system: str
    action: str
    env: str = "dev"
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class AdapterPreview(BaseModel):
    """AdapterPreview 类。"""
    task_id: str
    system: str
    action: str
    env: str
    risk: str
    need_approval: bool
    will_do: list[str]
    blocked: bool = False
    reason: str | None = None


class AdapterResult(BaseModel):
    """AdapterResult 结果模型。"""
    task_id: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class AdapterStatus(BaseModel):
    """AdapterStatus 状态模型。"""
    task_id: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class YunxiaoTaskCallback(BaseModel):
    """YunxiaoTaskCallback 类。"""
    task_id: str = Field(alias="taskId")
    operator: str = "yunxiao"
    host_id: str = Field(alias="hostId")
    env: str = "dev"
    execute: bool = False
    approval_id: str | None = Field(default=None, alias="approvalId")
    approved: bool = False
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class YunxiaoPipelineFailureCallback(BaseModel):
    """YunxiaoPipelineFailureCallback 类。"""
    task_id: str = Field(alias="taskId")
    workflow_id: str | None = Field(default=None, alias="workflowId")
    pipeline_id: str = Field(alias="pipelineId")
    build_number: str = Field(alias="buildNumber")
    stage_name: str = Field(alias="stageName")
    branch_name: str | None = Field(default=None, alias="branchName")
    commit_id: str | None = Field(default=None, alias="commitId")
    commit_message: str | None = Field(default=None, alias="commitMessage")
    operator: str = "yunxiao"
    exit_code: int | None = Field(default=None, alias="exitCode")
    log_tail: str = Field(default="", alias="logTail")
    log_url: str | None = Field(default=None, alias="logUrl")
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class WorkflowStartRequest(BaseModel):
    """WorkflowStartRequest 请求模型。"""
    dingtalk_url: str = Field(alias="dingtalkUrl")
    requirement_key: str | None = Field(default=None, alias="requirementKey")
    repo_url: str | None = Field(default=None, alias="repoUrl")
    branch_name: str | None = Field(default=None, alias="branchName")
    operator: str = "codex"
    context: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class WorkflowAdvanceRequest(BaseModel):
    """WorkflowAdvanceRequest 请求模型。"""
    operator: str = "codex"
    config_name: str | None = Field(default=None, alias="configName")
    kind: str | None = None
    sheet_id: str | None = Field(default=None, alias="sheetId")
    workbook_id: str | None = Field(default=None, alias="workbookId")
    range: str = "A1:J50"
    timeout: int = Field(default=60, ge=5, le=180)
    close_task_refs: list[str] = Field(default_factory=list, alias="closeTaskRefs")

    model_config = {"populate_by_name": True}


class WorkflowResolveRequest(BaseModel):
    """WorkflowResolveRequest 请求模型。"""
    operator: str = "codex"
    target_status: str = Field(alias="targetStatus")
    reason: str | None = None
    project_name: str | None = Field(default=None, alias="projectName")
    project_id: str | None = Field(default=None, alias="projectId")

    model_config = {"populate_by_name": True}


class WorkflowRetryRequest(BaseModel):
    """WorkflowRetryRequest 请求模型。"""
    operator: str = "codex"
    target_status: str = Field(default="CODING_REQUESTED", alias="targetStatus")
    reason: str | None = None
    max_retry_count: int = Field(default=3, alias="maxRetryCount", ge=1, le=10)

    model_config = {"populate_by_name": True}


class WorkflowRequirementItem(BaseModel):
    """WorkflowRequirementItem 数据模型。"""
    item_index: int | None = Field(default=None, alias="itemIndex")
    title: str
    parent_demand_index: int | None = Field(default=None, alias="parentDemandIndex")
    parent_demand_title: str | None = Field(default=None, alias="parentDemandTitle")
    owner_name: str | None = Field(default=None, alias="ownerName")
    content_lines: list[str] = Field(default_factory=list, alias="contentLines")

    model_config = {"populate_by_name": True}


class WorkflowRequirementDemand(BaseModel):
    """WorkflowRequirementDemand 数据模型。"""
    demand_index: int | None = Field(default=None, alias="demandIndex")
    title: str
    description: str | None = None
    items: list[WorkflowRequirementItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WorkflowRequirementRequest(BaseModel):
    """WorkflowRequirementRequest 请求模型。"""
    operator: str = "codex"
    summary: str | None = None
    document_title: str | None = Field(default=None, alias="documentTitle")
    version: str | None = None
    source_url: str | None = Field(default=None, alias="sourceUrl")
    demands: list[WorkflowRequirementDemand] = Field(default_factory=list)
    assignee_id: str | None = Field(default=None, alias="assigneeId")
    assignee_name: str | None = Field(default=None, alias="assigneeName")
    acceptance_criteria: list[str] = Field(default_factory=list, alias="acceptanceCriteria")
    affected_repos: list[str] = Field(default_factory=list, alias="affectedRepos")
    api_changes: list[dict[str, Any]] = Field(default_factory=list, alias="apiChanges")
    test_scope: list[str] = Field(default_factory=list, alias="testScope")
    risk: str | None = None
    open_questions: list[str] = Field(default_factory=list, alias="openQuestions")
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class WorkflowCodingResultRequest(BaseModel):
    """WorkflowCodingResultRequest 请求模型。"""
    operator: str = "codex"
    branch_name: str | None = Field(default=None, alias="branchName")
    commit_id: str | None = Field(default=None, alias="commitId")
    merge_request_url: str | None = Field(default=None, alias="mergeRequestUrl")
    summary: str | None = None
    tests: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class YunxiaoWorkitemDeleteRequest(BaseModel):
    """YunxiaoWorkitemDeleteRequest 请求模型。"""
    operator: str = "codex"
    project_name: str | None = Field(default=None, alias="projectName")
    workflow_id: str | None = Field(default=None, alias="workflowId")
    workitem_ids: list[str] = Field(default_factory=list, alias="workitemIds")
    include_demands: bool = Field(default=False, alias="includeDemands")
    dry_run: bool = Field(default=True, alias="dryRun")

    model_config = {"populate_by_name": True}
