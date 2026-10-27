#!/usr/bin/env bash
# =====================================================================
#  AWB Status Dashboard - install on a Linux server (Ubuntu/Debian/CentOS/Amazon Linux)
#
#  1. Copy the zip to the server and unzip it
#  2. Run:   sudo bash install-on-server.sh
#  3. Open the address it prints, and fill in the Setup page.
#
#  Run it again any time to update - your settings are kept.
#  Uses port 8010 so it can run next to the Smart Tracking Dashboard (port 8000).
# =====================================================================
set -eu
PORT="${PORT:-8010}"
APP_DIR=/opt/awb-status-dashboard
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-root}"

if [ "$(id -u)" -ne 0 ]; then echo "Please run with sudo:   sudo bash install-on-server.sh"; exit 1; fi
step() { echo; echo ">> $*"; }

step "Installing Python (if needed)"
if command -v apt-get >/dev/null 2>&1; then
  { apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip; } >/dev/null 2>&1 || \
    echo "   (couldn't reach the package mirror - continuing with the Python already installed)"
elif command -v dnf >/dev/null 2>&1; then dnf install -y -q python3 python3-pip >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then yum install -y -q python3 python3-pip >/dev/null 2>&1 || true
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "[FAIL] Python 3.9 or newer is needed; this server has $(python3 -V 2>&1)."; exit 1; }

step "Copying the app to $APP_DIR"
mkdir -p "$APP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  if [ -f "$APP_DIR/.env" ]; then cp "$APP_DIR/.env" /tmp/awb-dashboard.env.keep; fi
  cp -a "$SRC_DIR"/. "$APP_DIR"/
  if [ -f /tmp/awb-dashboard.env.keep ]; then mv /tmp/awb-dashboard.env.keep "$APP_DIR/.env"; fi
fi
rm -f "$APP_DIR/.venv/.requirements.sha" 2>/dev/null || true
chown -R "$RUN_USER":"$(id -gn "$RUN_USER")" "$APP_DIR"

step "Installing the app's packages (about a minute)"
sudo -u "$RUN_USER" -H python3 "$APP_DIR/start.py" --check >/tmp/awb-dashboard-install.log 2>&1 || true
if [ ! -f "$APP_DIR/.venv/.requirements.sha" ]; then
  echo "[FAIL] Installing the app's packages failed. Details:"
  tail -20 /tmp/awb-dashboard-install.log
  echo
  echo "Most common cause: this server can't reach pypi.org (no internet or a proxy)."
  exit 1
fi

step "Starting it as a background service (starts automatically after reboot)"
cat > /etc/systemd/system/awb-dashboard.service <<UNIT
[Unit]
Description=AWB Status Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/start.py --server --skip-install --port $PORT
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Kolkata

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable awb-dashboard >/dev/null 2>&1
systemctl restart awb-dashboard

step "Opening port $PORT in the firewall (if one is active)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then ufw allow "$PORT"/tcp >/dev/null && echo "   ufw: port $PORT allowed"; fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT"/tcp >/dev/null && firewall-cmd --reload >/dev/null && echo "   firewalld: port $PORT allowed"; fi

sleep 4
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PUBLIC_IP=$(curl -s --max-time 4 https://checkip.amazonaws.com 2>/dev/null || true)
if curl -s --max-time 5 "http://127.0.0.1:$PORT/api/config" >/dev/null; then
  echo
  echo "=================================================================="
  echo "  DONE - the dashboard is running."
  echo
  echo "  Open in your browser:"
  [ -n "$PUBLIC_IP" ] && echo "     http://$PUBLIC_IP:$PORT        (from anywhere)"
  [ -n "$LOCAL_IP" ]  && echo "     http://$LOCAL_IP:$PORT        (from the office network)"
  echo
  echo "  The first time, it shows a Setup page to connect your databases."
  echo
  echo "  If the page doesn't open: allow port $PORT in your cloud firewall"
  echo "  (AWS: EC2 > Security Groups > Inbound rules > add TCP $PORT)."
  echo
  echo "  Useful commands:"
  echo "     sudo systemctl restart awb-dashboard     restart"
  echo "     sudo journalctl -u awb-dashboard -n 50   see recent logs"
  echo "=================================================================="
else
  echo "[FAIL] The service did not start. Recent logs:"
  journalctl -u awb-dashboard -n 30 --no-pager || true
  exit 1
fi
