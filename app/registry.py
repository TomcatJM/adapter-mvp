from app.adapters.base import Adapter
from app.adapters.ssh_adapter import SshAdapter


class AdapterRegistry:
    """适配器注册表。"""
    def __init__(self) -> None:
        """初始化对象。"""
        self._adapters: list[Adapter] = [SshAdapter()]

    def find(self, system: str, action: str) -> Adapter:
        """查找。"""
        for adapter in self._adapters:
            if adapter.supports(system, action):
                return adapter
        raise ValueError(f"No adapter registered for {system}.{action}")


registry = AdapterRegistry()

