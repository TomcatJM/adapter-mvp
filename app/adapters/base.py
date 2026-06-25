from abc import ABC, abstractmethod

from app.models import AdapterPreview, AdapterRequest, AdapterResult, AdapterStatus


class Adapter(ABC):
    """Adapter 适配器。"""

    @abstractmethod
    def supports(self, system: str, action: str) -> bool:
        """判断当前适配器是否支持该动作。"""
        raise NotImplementedError

    @abstractmethod
    def preview(self, request: AdapterRequest) -> AdapterPreview:
        """预览动作，不执行真实远端操作。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: AdapterRequest) -> AdapterResult:
        """执行动作。"""
        raise NotImplementedError

    def status(self, task_id: str) -> AdapterStatus:
        """查询任务状态。"""
        return AdapterStatus(task_id=task_id, status="UNKNOWN", message="No status backend configured")
