#!/usr/bin/env bash
# Linux / macOS launcher for the Marauder V8 Control GUI.
# The app is pure Python + Tkinter, so it runs from source on any OS.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# Tkinter check (often a separate package on Linux: e.g. apt install python3-tk)
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "Tkinter is missing. On Debian/Ubuntu:  sudo apt install python3-tk" >&2
  exit 1
fi

# Install deps on first run if pyserial isn't present.
if ! "$PY" -c "import serial" 2>/dev/null; then
  echo "Installing dependencies (pyserial, esptool)…"
  "$PY" -m pip install --user -r requirements.txt
fi

# On Linux your user usually needs serial access:  sudo usermod -a -G dialout $USER  (then re-login)
exec "$PY" marauder_gui.py
