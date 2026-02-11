#!/bin/sh
MSG_FILE=$1
MSG=$(cat "$MSG_FILE")

if ! echo "$MSG" | grep -Eq '^[a-z]+(\(.+\))?!?: .+'; then
  echo "[ERROR] Commit message must follow Conventional Commits format (e.g., 'feat: message', 'fix(scope): message', 'refactor!: breaking change')."
  echo "Commit message was: $MSG"
  echo "Please correct the commit message and try again."
  exit 1
fi
