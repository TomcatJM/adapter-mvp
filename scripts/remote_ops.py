import argparse
from pathlib import Path
import sys

import paramiko

from import_inventory import read_xls_with_excel_com


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("op", choices=["status", "tail-audit", "restart"])
    parser.add_argument("--source", default=r"D:\document\up\user-password.xls")
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--lines", type=int, default=80)
    args = parser.parse_args()

    row = read_xls_with_excel_com(Path(args.source))[args.row]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(row["ip"], username=row["账号"], password=row["密码"], timeout=20)
    try:
        command = command_for(args.op, args.lines)
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


def command_for(op: str, lines: int) -> str:
    if op == "status":
        return (
            "systemctl status adapter-mvp --no-pager -l | head -n 60; "
            "echo '--- health ---'; curl -sS --max-time 10 http://127.0.0.1:18080/health; "
            "echo; echo '--- logrotate ---'; cat /etc/logrotate.d/adapter-mvp"
        )
    if op == "tail-audit":
        return f"tail -n {int(lines)} /opt/adapter-mvp/logs/audit.jsonl"
    if op == "restart":
        return (
            "systemctl restart adapter-mvp; sleep 1; "
            "systemctl is-active adapter-mvp; "
            "curl -sS --max-time 10 http://127.0.0.1:18080/health"
        )
    raise ValueError(op)


def mask(text: str) -> str:
    masked_lines = []
    for line in text.splitlines():
        if "PASSWORD=" in line or "TOKEN=" in line:
            key = line.split("=", 1)[0]
            masked_lines.append(f"{key}=***MASKED***")
        else:
            masked_lines.append(line)
    return "\n".join(masked_lines) + ("\n" if text.endswith("\n") else "")


if __name__ == "__main__":
    main()
