#!/bin/bash
# BoltPocket deployment setup script.
# Run as root on a fresh Ubuntu 22.04+ or Debian 12+ server.
#
# Prerequisites:
#   - PostgreSQL installed and running
#   - Redis installed and running
#   - Electrum daemon running with RPC enabled
#   - nginx installed (optional but recommended)
#
# Usage: sudo bash deploy/setup.sh

set -e

INSTALL_DIR="/home/boltpocket"
SERVICE_USER="boltpocket"

echo "=== BoltPocket Setup ==="
echo ""

# --- System user ---
if id "$SERVICE_USER" &>/dev/null; then
    echo "✓ User '$SERVICE_USER' already exists"
else
    echo "→ Creating system user '$SERVICE_USER'..."
    adduser --system --group --home "$INSTALL_DIR" --shell /bin/bash --no-create-home "$SERVICE_USER"
fi

# --- Python venv ---
if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "→ Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi

echo "→ Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# --- Local settings ---
if [ ! -f "$INSTALL_DIR/boltpocket/local_settings.py" ]; then
    echo "→ Creating local_settings.py from template..."
    cp "$INSTALL_DIR/boltpocket/local_settings.example.py" "$INSTALL_DIR/boltpocket/local_settings.py"
    echo ""
    echo "  ⚠️  Edit $INSTALL_DIR/boltpocket/local_settings.py with your:"
    echo "     - Database credentials"
    echo "     - Electrum RPC URL"
    echo "     - LNURL domain"
    echo "     - Admin Telegram bot token (optional)"
    echo ""
fi

# --- Database migrations ---
echo "→ Running database migrations..."
cd "$INSTALL_DIR"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python3" manage.py migrate --run-syncdb 2>&1 | grep -v "No migrations to apply" || true

# --- Static files ---
echo "→ Collecting static files..."
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python3" manage.py collectstatic --noinput 2>/dev/null || true

# --- File ownership ---
echo "→ Setting file ownership..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# --- Systemd services ---
echo "→ Installing systemd services..."
# Remove old combined service if present
systemctl stop boltpocket-celery 2>/dev/null || true
systemctl disable boltpocket-celery 2>/dev/null || true
rm -f /etc/systemd/system/boltpocket-celery.service

cp "$INSTALL_DIR/deploy/boltpocket-web.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/boltpocket-worker.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/boltpocket-beat.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable boltpocket-web boltpocket-worker boltpocket-beat

echo "→ Starting services..."
systemctl restart boltpocket-beat boltpocket-worker boltpocket-web

sleep 3

# --- Verify ---
echo ""
echo "=== Status ==="
systemctl is-active boltpocket-web && echo "  ✓ Web server running" || echo "  ✗ Web server failed"
systemctl is-active boltpocket-worker && echo "  ✓ Celery worker running" || echo "  ✗ Celery worker failed"
systemctl is-active boltpocket-beat && echo "  ✓ Celery beat running" || echo "  ✗ Celery beat failed"

echo ""
echo "=== Next Steps ==="
echo "  1. Edit local_settings.py if you haven't already"
echo "  2. Configure nginx as reverse proxy (see deploy/nginx.example.conf)"
echo "  3. Set up HTTPS (Let's Encrypt or Cloudflare Tunnel)"
echo "  4. Create an admin user: sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 manage.py createsuperuser"
echo "  5. Visit http://127.0.0.1:8000/admin/ to configure"
echo ""
echo "  Logs:  journalctl -u boltpocket-web -f"
echo "         journalctl -u boltpocket-worker -f"
echo "         journalctl -u boltpocket-beat -f"
echo "  Reload after code changes: bash scripts/reload.sh"
echo ""
echo "✓ Setup complete"
