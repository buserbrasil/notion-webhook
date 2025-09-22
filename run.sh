#!/bin/bash

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. Install it from https://github.com/astral-sh/uv"
    exit 1
fi

set -euo pipefail

# Quell third-party deprecation chatter while upstream transitions imports
export PYTHONWARNINGS=${PYTHONWARNINGS:-'ignore:Please use `import python_multipart` instead.:PendingDeprecationWarning'}

# Sync dependencies (runtime + dev). Enable postgres extras when requested.
SYNC_ARGS=("--extra" "dev")
if [ "${USE_POSTGRES:-0}" = "1" ]; then
    SYNC_ARGS+=("--extra" "postgres")
fi

echo "Syncing dependencies with uv..."
uv sync "${SYNC_ARGS[@]}"

case "${1:-serve}" in
  test)
    shift
    echo "Running tests..."
    uv run pytest "$@"
    ;;
  serve)
    shift
    echo "Starting the application..."
    uv run uvicorn app.main:app --reload "$@"
    ;;
  *)
    echo "Usage: $0 [serve|test]"
    exit 1
    ;;
esac
