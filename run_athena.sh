#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo ".venv not found. Run ./bootstrap.sh first."
  exit 1
fi

source .venv/bin/activate
python3 main.py
