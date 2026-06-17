"""
Optional non-interactive deployment path.

This script uses the password from the workbook without printing it, but it
requires paramiko to be installed in the local Python environment.
"""

import argparse
import getpass
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

try:
    import paramiko
except ImportError as exc:
    raise SystemExit("paramiko is not installed. Use deploy_from_excel.ps1 or install paramiko.") from exc

from import_inventory import read_xls_with_excel_com


ROOT = Path(__file__).resolve().parents[1]


def build_package() -> Path:
    out = ROOT / "adapter-mvp.tar.gz"
    if out.exists():
        out.unlink()
    with tarfile.open(out, "w:gz") as tar:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if rel.parts and rel.parts[0] in {".venv", "secrets", "logs"}:
                continue
            if path == out:
                continue
            tar.add(path, arcname=str(rel))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=r"D:\document\up\user-password.xls")
    parser.add_argument("--row", type=int, default=0, help="Zero-based data row index")
    parser.add_argument("--remote-dir", default="/opt/adapter-mvp")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    rows = read_xls_with_excel_com(Path(args.source))
    row = rows[args.row]
    ip = row["ip"]
    username = row["账号"]
    password = row["密码"]

    package = build_package()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, username=username, password=password, timeout=15)

    with ssh.open_sftp() as sftp:
        try:
            sftp.mkdir(args.remote_dir)
        except OSError:
            pass
        remote_package = f"{args.remote_dir}/adapter-mvp.tar.gz"
        sftp.put(str(package), remote_package)

    commands = [
        f"cd {args.remote_dir} && tar -xzf adapter-mvp.tar.gz",
        f"cd {args.remote_dir} && chmod +x scripts/remote_install.sh",
        f"cd {args.remote_dir} && APP_DIR={args.remote_dir} PORT={args.port} bash scripts/remote_install.sh",
    ]
    for command in commands:
        stdin, stdout, stderr = ssh.exec_command(command)
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise SystemExit(stderr.read().decode("utf-8", errors="replace"))
        print(stdout.read().decode("utf-8", errors="replace"))
    ssh.close()


if __name__ == "__main__":
    main()
