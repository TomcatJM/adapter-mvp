"""
Sync local Adapter env file to remote /etc/adapter-mvp/adapter-mvp.env and restart service.

The script never prints env values. Keep local env files under secrets/; that folder is git-ignored.
"""

import argparse
from pathlib import Path
import shlex
import sys

import paramiko

from import_inventory import read_xls_with_excel_com


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_ENV = ROOT / "secrets" / "adapter-mvp.env.local"
REMOTE_ENV = "/etc/adapter-mvp/adapter-mvp.env"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=r"D:\document\up\user-password.xls")
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--local-env", default=str(DEFAULT_LOCAL_ENV))
    args = parser.parse_args()

    local_env = Path(args.local_env)
    if not local_env.exists():
        raise SystemExit(f"Local env file not found: {local_env}")
    content = local_env.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    validate_env(content)

    row = read_xls_with_excel_com(Path(args.source))[args.row]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(row["ip"], username=row["账号"], password=row["密码"], timeout=20)
    try:
        command = build_remote_command(content)
        stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out:
            print(mask(out), end="")
        if err:
            print(mask(err), file=sys.stderr, end="")
        raise SystemExit(code)
    finally:
        ssh.close()


def validate_env(content: str) -> None:
    for idx, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise SystemExit(f"Invalid env line {idx}: missing '='")
        key = stripped.split("=", 1)[0]
        if not key.replace("_", "").isalnum() or not key[0].isalpha():
            raise SystemExit(f"Invalid env key at line {idx}: {key}")


def build_remote_command(content: str) -> str:
    quoted = shlex.quote(content)
    return (
        "set -euo pipefail; "
        "mkdir -p /etc/adapter-mvp; "
        f"printf %s {quoted} > {REMOTE_ENV}; "
        f"chmod 600 {REMOTE_ENV}; "
        "systemctl restart adapter-mvp; "
        "sleep 1; "
        "systemctl is-active adapter-mvp; "
        "curl -sS --max-time 10 http://127.0.0.1:18080/health"
    )


def mask(text: str) -> str:
    masked = []
    for line in text.splitlines():
        if any(word in line.upper() for word in ("TOKEN=", "PASSWORD=", "SECRET=", "KEY=")):
            masked.append(line.split("=", 1)[0] + "=***MASKED***")
        else:
            masked.append(line)
    return "\n".join(masked) + ("\n" if text.endswith("\n") else "")


if __name__ == "__main__":
    main()
