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
