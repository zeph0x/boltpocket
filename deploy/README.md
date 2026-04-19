# Deployment

Everything needed to run BoltPocket on a Linux server (Ubuntu 22.04+, Debian 12+).

## Prerequisites

- **Python 3.10+**
- **PostgreSQL** — database
- **Redis** — celery broker + price cache
- **Electrum** — Lightning/on-chain backend (running as daemon with RPC)
- **nginx** — reverse proxy (recommended)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/zeph0x/boltpocket.git /home/boltpocket
cd /home/boltpocket

# Run setup (as root)
sudo bash deploy/setup.sh
```

The setup script will:
1. Create a `boltpocket` system user
2. Set up the Python virtualenv and install dependencies
3. Create `local_settings.py` from template (edit with your credentials)
4. Run database migrations
5. Install and start systemd services
6. Set file ownership

## Services

| Service | Description | Port |
|---------|-------------|------|
| `boltpocket-web` | Gunicorn web server | 127.0.0.1:8000 |
| `boltpocket-worker` | Celery worker (task execution) | — |
| `boltpocket-beat` | Celery beat (task scheduler) | — |

Beat and worker run as **separate processes** so systemd can restart each independently.
If the worker crashes (e.g. Redis reconnection failure), it auto-restarts within 10 seconds
without affecting the scheduler, and vice versa.

All services use `Restart=always`.

## Configuration

Edit `/home/boltpocket/boltpocket/local_settings.py`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'boltpocket',
        'USER': 'boltpocket',
        'PASSWORD': 'your-password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

ELECTRUM_RPC_URL = 'http://user:pass@127.0.0.1:7777'
LNURL_DOMAIN = 'your-server.com'

# Optional: admin alerts via Telegram
ADMIN_TELEGRAM_BOT_TOKEN = ''
ADMIN_TELEGRAM_CHAT_ID = ''
```

## nginx

```bash
sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/boltpocket
sudo ln -s /etc/nginx/sites-available/boltpocket /etc/nginx/sites-enabled/
# Edit server_name and SSL paths
sudo nginx -t && sudo systemctl reload nginx
```

## HTTPS

Options:
- **Let's Encrypt**: `sudo certbot --nginx -d your-server.com`
- **Cloudflare Tunnel**: Free, stable URL, no port forwarding needed

NFC card tap URLs must be **public + HTTPS** since they're baked into card NFC data.

## Management Commands

```bash
# After code changes
bash scripts/reload.sh

# Manual service control
sudo systemctl restart boltpocket-beat boltpocket-worker boltpocket-web
sudo systemctl status boltpocket-web
sudo systemctl status boltpocket-worker
sudo systemctl status boltpocket-beat

# Logs
sudo journalctl -u boltpocket-web -f
sudo journalctl -u boltpocket-worker -f
sudo journalctl -u boltpocket-beat -f

# All logs combined
sudo journalctl -u 'boltpocket-*' -f

# Create admin user
sudo -u boltpocket /home/boltpocket/venv/bin/python3 manage.py createsuperuser

# Django shell
sudo -u boltpocket /home/boltpocket/venv/bin/python3 manage.py shell
```

## Troubleshooting

### Worker dies but beat keeps running (or vice versa)
This is exactly why they're split — systemd restarts the failed process independently.
Check logs: `journalctl -u boltpocket-worker --since "1 hour ago"`

### Tasks scheduled but never executed
Worker is down. Check: `systemctl status boltpocket-worker`

### Redis connection errors
If Redis restarts, both worker and beat will reconnect automatically (systemd restart).
Check Redis: `redis-cli ping`

## File Layout

```
/home/boltpocket/
├── boltpocket/          # Django project settings
│   ├── settings.py
│   ├── local_settings.py  (your config, gitignored)
│   └── celery.py
├── accounts/            # Core: accounts, transactions, payments
├── wallets/             # Wallet UI, bolt card endpoints
├── prices/              # BTC price feed (Kraken)
├── deploy/              # This directory
│   ├── setup.sh         # One-command deployment
│   ├── boltpocket-web.service
│   ├── boltpocket-worker.service
│   ├── boltpocket-beat.service
│   └── nginx.example.conf
├── scripts/             # reload.sh, card print tools
├── firmware/            # M5Stack e-ink display firmware
├── venv/                # Python virtualenv
└── manage.py
```

## Security Notes

- Gunicorn binds to `127.0.0.1:8000` — not exposed directly
- Services run as unprivileged `boltpocket` user
- Electrum runs separately (as root or its own user)
- Store `local_settings.py` securely — contains DB password and API keys
- NFC card secrets are stored encrypted in the database
