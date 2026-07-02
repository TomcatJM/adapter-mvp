#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/codegraph-worker}"
CACHE_DIR="${CACHE_DIR:-/opt/codegraph-cache}"
SERVICE_NAME="${SERVICE_NAME:-codegraph-worker}"
PORT="${PORT:-18081}"
ENV_FILE="${ENV_FILE:-/etc/adapter-mvp/codegraph-worker.env}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! command -v codegraph >/dev/null 2>&1; then
  echo "codegraph is required; install CodeGraph CLI before starting ${SERVICE_NAME}" >&2
  exit 1
fi

if ! command -v ossutil >/dev/null 2>&1; then
  echo "ossutil is required; install Aliyun ossutil before starting ${SERVICE_NAME}" >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$CACHE_DIR" /etc/adapter-mvp
cd "$APP_DIR"

python3 -m venv .venv
".venv/bin/pip" install --upgrade pip >/dev/null
".venv/bin/pip" install -r requirements.txt

if [ ! -f "$ENV_FILE" ]; then
  cat >"$ENV_FILE" <<EOF
CODEGRAPH_WORKER_CACHE_ROOT=${CACHE_DIR}
CODEGRAPH_WORKER_OSSUTIL_BIN=$(command -v ossutil)
CODEGRAPH_WORKER_CODEGRAPH_BIN=$(command -v codegraph)
EOF
  chmod 600 "$ENV_FILE"
fi

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=CodeGraph Worker
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/uvicorn codegraph_worker.main:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=5
MemoryMax=1536M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager

echo "CodeGraph Worker started on 127.0.0.1:${PORT}"
