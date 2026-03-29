#!/bin/bash
# Force-restart celery worker+beat. Kills zombies, starts fresh.
# Safe to run from cron or manually.

set -e
cd /home/boltpocket

echo "$(date '+%Y-%m-%d %H:%M:%S') → Killing celery processes..."
pkill -9 -f "celery -A boltpocket" 2>/dev/null || true
sleep 2

# Clean up stale pidfiles/schedule
rm -f celerybeat-schedule celerybeat.pid 2>/dev/null || true

echo "$(date '+%Y-%m-%d %H:%M:%S') → Starting celery in tmux..."
tmux send-keys -t celery "cd /home/boltpocket && source venv/bin/activate && celery -A boltpocket worker --beat -l info" Enter

echo "$(date '+%Y-%m-%d %H:%M:%S') ✓ Celery restarted"
