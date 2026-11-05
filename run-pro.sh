#!/usr/bin/env bash
set -euo pipefail
app_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pro_root=${MARAUDER_PRO_DIR:-"$app_root/../MarauderGUIPro"}
if [[ -f "$pro_root/marauder_pro/__init__.py" ]]; then
  export PYTHONPATH="$pro_root${PYTHONPATH:+:$PYTHONPATH}"
fi
cd "$app_root"
exec "${PYTHON:-python3}" marauder_workspace.py "$@"
