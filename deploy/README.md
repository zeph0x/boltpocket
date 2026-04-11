# Deployment

Systemd service files for running BoltPocket on a Linux server.

## Services

| Service | Description |
|---------|-------------|
| `boltpocket-web.service` | Django web server (gunicorn on 127.0.0.1:8000) |
| `boltpocket-celery.service` | Celery worker + beat (background tasks, recurring payments) |

## Quick Setup

```bash
# Copy service files
sudo cp deploy/boltpocket-*.service /etc/systemd/system/

# Edit paths/user if your install differs from /home/boltpocket
sudo nano /etc/systemd/system/boltpocket-web.service
sudo nano /etc/systemd/system/boltpocket-celery.service

# Reload systemd, enable and start
sudo systemctl daemon-reload
sudo systemctl enable boltpocket-web boltpocket-celery
sudo systemctl start boltpocket-web boltpocket-celery
```

## Check Status

```bash
sudo systemctl status boltpocket-web
sudo systemctl status boltpocket-celery
```

## Logs

```bash
sudo journalctl -u boltpocket-web -f
sudo journalctl -u boltpocket-celery -f
```

## After Code Changes

```bash
bash scripts/reload.sh
# or manually:
sudo systemctl restart boltpocket-celery boltpocket-web
```

## Notes

- Both services use `Restart=always` — they auto-restart on crash.
- The web service uses gunicorn (install with `pip install gunicorn`).
- Default user is `boltpocket` — change to match your setup.
- Both bind to localhost only. Use nginx as a reverse proxy for HTTPS.
- Redis and PostgreSQL must be running before these services start.
