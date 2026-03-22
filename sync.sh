#!/bin/bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:-athena_pi@athena.local}"
TARGET_DIR="${TARGET_DIR:-/home/athena_pi/athena}"
SERVICE_NAME="athena-whisplay"

rsync -avz --delete \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='output' \
  --exclude='.env' \
  ./ "${TARGET_HOST}:${TARGET_DIR}/"

ssh "${TARGET_HOST}" "
  cd ${TARGET_DIR} && \
  python3 -m venv .venv && \
  . .venv/bin/activate && \
  pip install -r requirements.txt && \
  sudo cp athena-whisplay.service /etc/systemd/system/${SERVICE_NAME}.service && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable ${SERVICE_NAME} && \
  sudo systemctl restart ${SERVICE_NAME} && \
  sleep 2 && \
  sudo journalctl -u ${SERVICE_NAME} -n 30 --no-pager
"
