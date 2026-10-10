#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python3)
if command -v python3 >/dev/null 2>&1; then
  python3 -c 'import tkinter' >/dev/null 2>&1 || missing+=(python3-tk)
  python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || missing+=(python3-venv)
else
  missing+=(python3-tk python3-venv)
fi
if ((${#missing[@]})); then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Installing prerequisites: ${missing[*]}"
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
  else
    echo "Install Python 3.10-3.13, Tkinter, and venv using your package manager, then rerun." >&2
    exit 1
  fi
fi
python3 -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,14), sys.version'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
exec .venv/bin/python marauder_gui.py
