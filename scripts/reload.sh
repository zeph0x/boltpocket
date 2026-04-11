#!/bin/bash
# Reload BoltPocket after code changes.
# Restarts celery and web services via systemd.

set -e
cd /home/boltpocket

echo "→ Running migrations..."
source venv/bin/activate
python3 manage.py migrate --run-syncdb 2>&1 | grep -v "No migrations to apply" || true

echo "→ Restarting services..."
systemctl restart boltpocket-celery boltpocket-web

echo "✓ Done"
