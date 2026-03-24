#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Bootstrap complete."
echo "Next:"
echo "  1. Edit .env and add your OPENAI_API_KEY"
echo "  2. On a Pi, run: sudo python3 /home/athena_pi/athena/main.py"
echo "  3. Optional helper check: source .venv/bin/activate && python3 demo_runner.py check"
echo "  4. Optional prompt regression check: source .venv/bin/activate && python3 demo_runner.py prompt-check"
