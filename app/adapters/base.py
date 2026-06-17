from abc import ABC, abstractmethod

from app.models import AdapterPreview, AdapterRequest, AdapterResult, AdapterStatus


class Adapter(ABC):
    @abstractmethod
    def supports(self, system: str, action: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def preview(self, request: AdapterRequest) -> AdapterPreview:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: AdapterRequest) -> AdapterResult:
        raise NotImplementedError

    def status(self, task_id: str) -> AdapterStatus:
        return AdapterStatus(task_id=task_id, status="UNKNOWN", message="No status backend configured")

