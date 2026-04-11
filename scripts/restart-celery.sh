#!/bin/bash
# Force-restart celery worker+beat via systemd.
# Safe to run from cron or manually.

echo "$(date '+%Y-%m-%d %H:%M:%S') → Restarting celery via systemd..."
systemctl restart boltpocket-celery
echo "$(date '+%Y-%m-%d %H:%M:%S') ✓ Celery restarted"
