#!/usr/bin/env bash
#
# Deploy Deep Valuation to an Ubuntu host behind Tailscale Serve.
# Idempotent: safe to re-run to pick up new commits.
#
#   sudo ./deploy/deploy.sh https://github.com/you/deep-valuation.git
#
set -euo pipefail

REPO_URL="${1:-}"
APP_ROOT="${APP_ROOT:-/opt/deepval}"
APP_DIR="$APP_ROOT/app"
VENV="$APP_ROOT/venv"
SVC_USER="deepval"
BIND_PORT="${BIND_PORT:-8010}"
SERVE_PORT="${SERVE_PORT:-8446}"

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

if [[ -z "$REPO_URL" && ! -d "$APP_DIR/.git" ]]; then
    echo "Usage: sudo $0 <repo-url>   (first run only)" >&2
    exit 1
fi

# --- service account -------------------------------------------------------
if ! id "$SVC_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$APP_ROOT" --shell /usr/sbin/nologin "$SVC_USER"
fi

# --- code ------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
    sudo -u "$SVC_USER" git -C "$APP_DIR" pull --ff-only
else
    sudo -u "$SVC_USER" git clone "$REPO_URL" "$APP_DIR"
fi

# --- dependencies ----------------------------------------------------------
# gunicorn is a deployment concern, so it is installed here rather than being
# pinned in requirements.txt alongside the app's own dependencies.
[[ -d "$VENV" ]] || sudo -u "$SVC_USER" python3 -m venv "$VENV"
sudo -u "$SVC_USER" "$VENV/bin/pip" install --upgrade pip
sudo -u "$SVC_USER" "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" gunicorn

# --- runtime directories ---------------------------------------------------
# Both are gitignored, so they never arrive with the clone.
sudo -u "$SVC_USER" mkdir -p "$APP_DIR/uploads" "$APP_DIR/outputs"

# --- service ---------------------------------------------------------------
install -m 644 "$APP_DIR/deploy/deepval.service" /etc/systemd/system/deepval.service
systemctl daemon-reload
systemctl enable --now deepval
systemctl restart deepval

# --- verify ----------------------------------------------------------------
sleep 2
systemctl is-active --quiet deepval || { journalctl -u deepval -n 40 --no-pager; exit 1; }
curl -fsS -o /dev/null "http://127.0.0.1:$BIND_PORT/"

echo
echo "deepval is up on 127.0.0.1:$BIND_PORT"
echo
echo "Expose it on the tailnet with:"
echo "  sudo tailscale serve --bg --https=$SERVE_PORT http://127.0.0.1:$BIND_PORT"
