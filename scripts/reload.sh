#!/bin/bash
# Reload BoltPocket after code changes.
# Restarts celery (worker+beat) and django runserver.

set -e
cd /home/boltpocket

echo "→ Running migrations..."
source venv/bin/activate
python3 manage.py migrate --run-syncdb 2>&1 | grep -v "No migrations to apply" || true

echo "→ Restarting celery..."
tmux send-keys -t celery C-c
sleep 3
tmux send-keys -t celery "cd /home/boltpocket && source venv/bin/activate && celery -A boltpocket worker --beat -l info" Enter

echo "→ Restarting django..."
tmux send-keys -t boltpocket C-c
sleep 2
tmux send-keys -t boltpocket "cd /home/boltpocket && source venv/bin/activate && python3 manage.py runserver 0.0.0.0:8000" Enter

echo "✓ Done"
