import json
import os
import socket
import time
from pathlib import Path

import paramiko

from app.adapters.base import Adapter
from app.models import AdapterPreview, AdapterRequest, AdapterResult
from app.security import action_policy, remote_execution_enabled


ROOT = Path(__file__).resolve().parents[2]
HOSTS_PATH = ROOT / "config" / "hosts.masked.json"
SECRETS_PATH = ROOT / "secrets" / "hosts.secrets.json"


class SshAdapter(Adapter):
    def supports(self, system: str, action: str) -> bool:
        return system == "ssh" and action in {"check_connectivity"}

    def preview(self, request: AdapterRequest) -> AdapterPreview:
        host = self._find_host(request.params.get("hostId"))
        policy = action_policy(request.system, request.action, request.env)
        blocked = host is None
        reason = None if host else "Unknown hostId"
        will_do = []
        if host:
            will_do = [
                f"Check SSH connectivity to {host['platform']} {host['ip']} as {host['account']}",
                "Read password from passwordRef secret only",
                "Do not print or return password",
            ]
        return AdapterPreview(
            task_id=request.task_id,
            system=request.system,
            action=request.action,
            env=request.env,
            risk="low" if request.env == "dev" else "medium",
            need_approval=bool(policy.get("need_approval", True)),
            will_do=will_do,
            blocked=blocked,
            reason=reason,
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        preview = self.preview(request)
        if preview.blocked:
            return AdapterResult(task_id=request.task_id, status="FAILED", message=preview.reason or "Blocked")
        if not remote_execution_enabled():
            return AdapterResult(
                task_id=request.task_id,
                status="WAIT_APPROVAL",
                message="Remote execution is disabled. Set ALLOW_REMOTE_EXEC=true only after approval.",
                data={"preview": preview.model_dump()},
            )

        host = self._find_host(request.params.get("hostId"))
        if host is None:
            return AdapterResult(task_id=request.task_id, status="FAILED", message="Unknown hostId")

        password = self._resolve_password(host.get("passwordRef"))
        if not password:
            return AdapterResult(
                task_id=request.task_id,
                status="FAILED",
                message="Missing SSH password secret for host passwordRef",
                data={"hostId": host.get("hostId"), "passwordRef": host.get("passwordRef")},
            )

        return self._check_connectivity(request.task_id, host, password, request.params)

    def _check_connectivity(
        self,
        task_id: str,
        host: dict,
        password: str,
        params: dict,
    ) -> AdapterResult:
        timeout = int(params.get("timeoutSeconds", 10))
        started = time.perf_counter()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host["ip"],
                username=host["account"],
                password=password,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return AdapterResult(
                task_id=task_id,
                status="SUCCESS",
                message="SSH connectivity check succeeded",
                data=self._safe_host_data(host, elapsed_ms),
            )
        except (paramiko.AuthenticationException, paramiko.SSHException, socket.error, TimeoutError) as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return AdapterResult(
                task_id=task_id,
                status="FAILED",
                message=f"SSH connectivity check failed: {exc.__class__.__name__}",
                data=self._safe_host_data(host, elapsed_ms),
            )
        finally:
            client.close()

    def _find_host(self, host_id: str | None) -> dict | None:
        if not host_id or not HOSTS_PATH.exists():
            return None
        with HOSTS_PATH.open("r", encoding="utf-8") as f:
            hosts = json.load(f).get("hosts", [])
        return next((host for host in hosts if host.get("hostId") == host_id), None)

    def _resolve_password(self, password_ref: str | None) -> str | None:
        if not password_ref:
            return None
        env_value = os.getenv(password_ref)
        if env_value:
            return env_value
        if not SECRETS_PATH.exists():
            return None
        with SECRETS_PATH.open("r", encoding="utf-8") as f:
            secrets = json.load(f)
        value = secrets.get(password_ref)
        return str(value) if value else None

    def _safe_host_data(self, host: dict, elapsed_ms: int) -> dict:
        return {
            "hostId": host.get("hostId"),
            "platform": host.get("platform"),
            "ip": host.get("ip"),
            "account": host.get("account"),
            "elapsedMs": elapsed_ms,
        }
