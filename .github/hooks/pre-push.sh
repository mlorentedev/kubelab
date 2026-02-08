#!/bin/bash
set -eu

echo "[INFO] Running pre-push checks..."
make lint
status=$?
if [ $status -ne 0 ]; then
  echo "[ERROR] Linting failed. Push aborted."
  exit $status
fi
echo "[SUCCESS] All checks passed. Proceeding with push."
