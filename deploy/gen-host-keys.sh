#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <hostname>"
  echo "Example: $0 production"
  exit 1
fi

HOST="$1"
TEMP_DIR=$(mktemp -d)

install -d -m755 "$TEMP_DIR/etc/ssh"

ssh-keygen -t ed25519 -f "$TEMP_DIR/etc/ssh/ssh_host_ed25519_key" -N "" -C "" -q

chmod 600 "$TEMP_DIR/etc/ssh/ssh_host_ed25519_key"
chmod 644 "$TEMP_DIR/etc/ssh/ssh_host_ed25519_key.pub"

PUB_KEY=$(cat "$TEMP_DIR/etc/ssh/ssh_host_ed25519_key.pub")
AGE_KEY=$(echo "$PUB_KEY" | ssh-to-age)

echo "$TEMP_DIR"
echo "- &$HOST $AGE_KEY"
