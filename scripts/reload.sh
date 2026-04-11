#!/bin/bash
# Reload BoltPocket after code changes.
# Restarts celery (worker+beat) and django runserver.

set -e
cd /home/boltpocket

echo "→ Running migrations..."
source venv/bin/activate
python3 manage.py migrate --run-syncdb 2>&1 | grep -v "No migrations to apply" || true

echo "→ Restarting celery..."
systemctl restart boltpocket-celery

echo "→ Restarting django..."
tmux send-keys -t boltpocket C-c
sleep 2
tmux send-keys -t boltpocket "cd /home/boltpocket && source venv/bin/activate && python3 manage.py runserver 127.0.0.1:8000" Enter

echo "✓ Done"
