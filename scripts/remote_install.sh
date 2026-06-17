#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/adapter-mvp}"
SERVICE_NAME="${SERVICE_NAME:-adapter-mvp}"
PORT="${PORT:-18080}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

mkdir -p "$APP_DIR"
mkdir -p /etc/adapter-mvp
cd "$APP_DIR"

python3 -m venv .venv
".venv/bin/pip" install --upgrade pip >/dev/null
".venv/bin/pip" install -r requirements.txt

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Adapter MVP
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=ALLOW_REMOTE_EXEC=false
EnvironmentFile=-/etc/adapter-mvp/adapter-mvp.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

cat >/etc/logrotate.d/${SERVICE_NAME} <<EOF
${APP_DIR}/logs/*.jsonl {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
EOF

systemctl status "${SERVICE_NAME}" --no-pager

echo "Adapter MVP started on port ${PORT}"
