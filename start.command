#!/bin/bash
# Double-click this file in Finder to start the draft assistant.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting things up..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || { echo "Setup failed."; read -r; exit 1; }
fi
exec .venv/bin/python -m draft_assistant "$@"
