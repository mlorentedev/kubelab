#!/bin/sh
MSG_FILE=$1
MSG=$(cat "$MSG_FILE")

if ! echo "$MSG" | grep -Eq '^[a-z]+: .+'; then
  echo "[ERROR] Commit message must start with a lowercase prefix followed by a colon and a space (e.g., 'chore: Your message here')."
  echo "Commit message was: $MSG"
  echo "Please correct the commit message and try again."
  exit 1
fi
