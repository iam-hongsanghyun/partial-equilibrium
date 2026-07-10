#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
STAMP="$VENV_DIR/.requirements-installed"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi

if [[ -f "$REQUIREMENTS" ]] && { [[ ! -f "$STAMP" ]] || [[ "$REQUIREMENTS" -nt "$STAMP" ]]; }; then
  echo "Installing requirements ..."
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$REQUIREMENTS"
  touch "$STAMP"
fi

if [[ "$#" -eq 0 ]]; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/ets_framework.py" --gui
fi

if [[ "$1" == "sample" ]]; then
  shift
  exec "$PYTHON_BIN" "$SCRIPT_DIR/ets_framework.py" --mode "${1:-banking}"
fi

if [[ "$1" == "samples" ]]; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/ets_framework.py" --list-modes
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/ets_framework.py" "$@"
