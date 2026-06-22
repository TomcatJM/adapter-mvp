from typing import Any

from pydantic import BaseModel, Field


class AdapterRequest(BaseModel):
    task_id: str = Field(alias="taskId")
    operator: str
    system: str
    action: str
    env: str = "dev"
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class AdapterPreview(BaseModel):
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
    task_id: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class AdapterStatus(BaseModel):
    task_id: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class YunxiaoTaskCallback(BaseModel):
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
    task_id: str = Field(alias="taskId")
    workflow_id: str | None = Field(default=None, alias="workflowId")
    pipeline_id: str = Field(alias="pipelineId")
    build_number: str = Field(alias="buildNumber")
    stage_name: str = Field(alias="stageName")
    branch_name: str | None = Field(default=None, alias="branchName")
    commit_id: str | None = Field(default=None, alias="commitId")
    operator: str = "yunxiao"
    exit_code: int | None = Field(default=None, alias="exitCode")
    log_tail: str = Field(default="", alias="logTail")
    log_url: str | None = Field(default=None, alias="logUrl")
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class WorkflowStartRequest(BaseModel):
    dingtalk_url: str = Field(alias="dingtalkUrl")
    requirement_key: str | None = Field(default=None, alias="requirementKey")
    repo_url: str | None = Field(default=None, alias="repoUrl")
    branch_name: str | None = Field(default=None, alias="branchName")
    operator: str = "codex"
    context: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class WorkflowAdvanceRequest(BaseModel):
    operator: str = "codex"
    config_name: str | None = Field(default=None, alias="configName")
    kind: str | None = None
    sheet_id: str | None = Field(default=None, alias="sheetId")
    workbook_id: str | None = Field(default=None, alias="workbookId")
    range: str = "A1:J50"
    timeout: int = Field(default=60, ge=5, le=180)

    model_config = {"populate_by_name": True}


class WorkflowResolveRequest(BaseModel):
    operator: str = "codex"
    target_status: str = Field(alias="targetStatus")
    reason: str | None = None

    model_config = {"populate_by_name": True}


class WorkflowRequirementRequest(BaseModel):
    operator: str = "codex"
    summary: str
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
    operator: str = "codex"
    branch_name: str | None = Field(default=None, alias="branchName")
    commit_id: str | None = Field(default=None, alias="commitId")
    merge_request_url: str | None = Field(default=None, alias="mergeRequestUrl")
    summary: str | None = None
    tests: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
