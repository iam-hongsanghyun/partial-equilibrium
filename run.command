#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer uv: it owns .venv and syncs the pinned environment (pyproject.toml +
# uv.lock — the same environment the golden-baseline gate certifies).
if command -v uv >/dev/null 2>&1; then
  echo "Syncing environment with uv ..."
  uv sync --all-extras
  PY=(uv run python)
else
  # Fallback: classic venv + pip from requirements.txt.
  VENV_DIR="$SCRIPT_DIR/.venv"
  PYTHON_BIN="$VENV_DIR/bin/python"
  REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
  STAMP="$VENV_DIR/.requirements-installed"

  if [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "Creating virtual environment in $VENV_DIR ..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi

  if [[ -f "$REQUIREMENTS" ]] && { [[ ! -f "$STAMP" ]] || [[ "$REQUIREMENTS" -nt "$STAMP" ]]; }; then
    echo "Installing the pe package (editable) ..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install -e ".[dev]"
    touch "$STAMP"
  fi
  PY=("$PYTHON_BIN")
fi

# Both paths editable-install the pe package (uv sync / pip install -e), so
# `-m pe.cli` resolves via the install — no PYTHONPATH=$SRC needed (WO-0). A
# split package is not sys.path-reconstructable; only the install carries it.

if [[ "$#" -eq 0 ]]; then
  exec "${PY[@]}" -m pe.cli --gui
fi

if [[ "$1" == "sample" ]]; then
  shift
  exec "${PY[@]}" -m pe.cli --mode "${1:-banking}"
fi

if [[ "$1" == "samples" ]]; then
  exec "${PY[@]}" -m pe.cli --list-modes
fi

exec "${PY[@]}" -m pe.cli "$@"
