#!/usr/bin/env bash
# Local launch script for Cove Universal Converter.
#
# Always uses the project's .venv interpreter so optional runtime
# dependencies (xhtml2pdf, pypdf, openpyxl, pillow-heif, …) are
# present. Refuses to fall back to system Python — silently launching
# without those deps is what produced the "TXT -> PDF fails at 60%"
# false alarm.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    cat >&2 <<EOF
error: .venv interpreter not found at: $VENV_PY

Set up the virtual environment first:

    python -m venv .venv
    .venv/bin/pip install -r requirements.txt

Then re-run: ./run.sh
EOF
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$VENV_PY" -m cove_converter "$@"
