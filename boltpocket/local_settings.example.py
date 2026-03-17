# Copy this file to local_settings.py and edit for your deployment.
# This file is imported at the end of settings.py and overrides defaults.

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'your-domain.com']

# Electrum RPC
ELECTRUM_WALLET_PATH = '/root/.electrum/wallets/default_wallet'
ELECTRUM_RPC_URL = 'http://user:password@127.0.0.1:7777'

# PostgreSQL (recommended for production)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'boltpocket',
        'USER': 'boltpocket',
        'PASSWORD': 'changeme',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Optional: admin alerts via Telegram
# ADMIN_TELEGRAM_BOT_TOKEN = 'your-bot-token'
# ADMIN_TELEGRAM_CHAT_ID = 'your-chat-id'

# LNURL domain — must match your public domain (used for lightning addresses)
LNURL_DOMAIN = 'your-domain.com'

# Reverse proxy settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = ['https://your-domain.com']

# Set to False in production
DEBUG = True
