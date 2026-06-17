from app.adapters.base import Adapter
from app.adapters.ssh_adapter import SshAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[Adapter] = [SshAdapter()]

    def find(self, system: str, action: str) -> Adapter:
        for adapter in self._adapters:
            if adapter.supports(system, action):
                return adapter
        raise ValueError(f"No adapter registered for {system}.{action}")


registry = AdapterRegistry()

