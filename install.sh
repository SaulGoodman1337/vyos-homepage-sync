#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/vyos-homepage-sync"
REPO_URL=""
BRANCH="main"
ENABLE_AUTO_UPDATE="false"
LOCAL_MODE="false"

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --repo URL             Git repository URL to install from
  --branch NAME          Git branch (default: main)
  --enable-auto-update   Enable daily updater timer
  --local                Install files from the current checkout
  -h, --help             Show this help

Examples:
  sudo ./install.sh --local
  sudo ./install.sh --repo https://github.com/USER/vyos-homepage-sync.git
  sudo ./install.sh --repo https://github.com/USER/vyos-homepage-sync.git --enable-auto-update
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO_URL="${2:?missing repo URL}"; shift 2 ;;
    --branch) BRANCH="${2:?missing branch}"; shift 2 ;;
    --enable-auto-update) ENABLE_AUTO_UPDATE="true"; shift ;;
    --local) LOCAL_MODE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git ca-certificates python3 python3-requests python3-yaml

if [[ "$LOCAL_MODE" == "true" ]]; then
  SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
  if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -a "$SOURCE_DIR"/. "$INSTALL_DIR"/
  fi
else
  if [[ -z "$REPO_URL" ]]; then
    echo "--repo is required unless --local is used." >&2
    exit 2
  fi
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
    git -C "$INSTALL_DIR" fetch --prune origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
  else
    rm -rf "$INSTALL_DIR"
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
  fi
fi

python3 -m py_compile "$INSTALL_DIR/src/vyos-homepage-sync.py"
bash -n "$INSTALL_DIR/install.sh"
bash -n "$INSTALL_DIR/update.sh"

install -m 0755 "$INSTALL_DIR/src/vyos-homepage-sync.py" /usr/local/sbin/vyos-homepage-sync
install -m 0755 "$INSTALL_DIR/update.sh" /usr/local/sbin/vyos-homepage-sync-update
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync.service" /etc/systemd/system/vyos-homepage-sync.service
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync.timer" /etc/systemd/system/vyos-homepage-sync.timer
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync-update.service" /etc/systemd/system/vyos-homepage-sync-update.service
install -m 0644 "$INSTALL_DIR/systemd/vyos-homepage-sync-update.timer" /etc/systemd/system/vyos-homepage-sync-update.timer

if [[ ! -f /etc/vyos-homepage-sync.conf ]]; then
  install -m 0600 "$INSTALL_DIR/config.env.example" /etc/vyos-homepage-sync.conf
  echo "Created /etc/vyos-homepage-sync.conf - edit VYOS_API_KEY before first run."
else
  chmod 0600 /etc/vyos-homepage-sync.conf
  echo "Keeping existing /etc/vyos-homepage-sync.conf"
fi

systemctl daemon-reload
systemctl enable --now vyos-homepage-sync.timer

if [[ "$ENABLE_AUTO_UPDATE" == "true" ]]; then
  systemctl enable --now vyos-homepage-sync-update.timer
else
  echo "Auto-update timer installed but not enabled."
  echo "Enable with: systemctl enable --now vyos-homepage-sync-update.timer"
fi

echo
echo "Installed vyos-homepage-sync."
echo "Configure: /etc/vyos-homepage-sync.conf"
echo "Test:      systemctl start vyos-homepage-sync.service"
echo "Logs:      journalctl -u vyos-homepage-sync.service -n 100 --no-pager"
echo "Update:    vyos-homepage-sync-update"
