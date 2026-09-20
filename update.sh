#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/vyos-homepage-sync"
BRANCH="${VYOS_HOMEPAGE_SYNC_BRANCH:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  echo "$INSTALL_DIR is not a git checkout." >&2
  echo "Reinstall using install.sh --repo https://github.com/USER/vyos-homepage-sync.git" >&2
  exit 1
fi

BEFORE="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
git -C "$INSTALL_DIR" fetch --prune origin "$BRANCH"
AFTER="$(git -C "$INSTALL_DIR" rev-parse "origin/$BRANCH")"

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "Already up to date: $BEFORE"
  exit 0
fi

echo "Updating $BEFORE -> $AFTER"
git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"

python3 -m py_compile "$INSTALL_DIR/src/vyos-homepage-sync.py"
bash -n "$INSTALL_DIR/install.sh"
bash -n "$INSTALL_DIR/update.sh"

install -m 0755 "$INSTALL_DIR/src/vyos-homepage-sync.py" /usr/local/sbin/vyos-homepage-sync
install -m 0755 "$INSTALL_DIR/update.sh" /usr/local/sbin/vyos-homepage-sync-update
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync.service" /etc/systemd/system/vyos-homepage-sync.service
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync.timer" /etc/systemd/system/vyos-homepage-sync.timer
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync-update.service" /etc/systemd/system/vyos-homepage-sync-update.service
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync-update.timer" /etc/systemd/system/vyos-homepage-sync-update.timer

systemctl daemon-reload
systemctl start vyos-homepage-sync.service

echo "Update complete."
