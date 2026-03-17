"""
Django settings for BoltPocket project.
"""

from pathlib import Path
import os
from django.contrib.messages import constants as messages


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve(strict=True).parents[1]

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts.apps.AccountsConfig',
    'wallets.apps.WalletsConfig',
    'prices.apps.PricesConfig',
    'crispy_forms',
    'crispy_bootstrap5',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
MESSAGE_TAGS = {
    messages.DEBUG: 'alert-secondary',
    messages.INFO: 'alert-info',
    messages.SUCCESS: 'alert-success',
    messages.WARNING: 'alert-warning',
    messages.ERROR: 'alert-danger',
}

ROOT_URLCONF = 'boltpocket.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'boltpocket.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'boltpocket'),
        'USER': os.environ.get('DB_USER', 'boltpocket'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'wallets.SystemUser'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = False
USE_TZ = True

# Electrum
ELECTRUM_WALLET_PATH = ""
ELECTRUM_RPC_URL = ""

# Redis / Celery
REDIS_URL = ""
CELERY_BROKER_URL = 'redis://localhost:6379'
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

CELERY_BEAT_SCHEDULE = {
    'price-feed': {
        'task': 'prices.tasks.price_feed',
        'schedule': 60.0,
    },
    'process-ln-payments': {
        'task': 'accounts.backends.electrum.ln_tasks.process_ln_payments',
        'schedule': 60.0,
    },
    'check-ln-incoming': {
        'task': 'accounts.backends.electrum.ln_tasks.check_ln_incoming',
        'schedule': 60.0,
    },
    'check-onchain-incoming': {
        'task': 'accounts.backends.electrum.tasks.electrum_check_incoming_txs',
        'schedule': 30.0,
    },
    'reconcile-ln-payments': {
        'task': 'accounts.backends.electrum.ln_tasks.reconcile_ln_payments',
        'schedule': 300.0,
    },
    'refill-address-queue': {
        'task': 'accounts.backends.electrum.tasks.electrum_refill_address_queue',
        'schedule': 3600.0,  # every hour
    },
    'process-onchain-outgoing': {
        'task': 'accounts.backends.electrum.tasks.process_onchain_outgoing',
        'schedule': 600.0,  # every 10 minutes
    },
    'process-recurring-payments': {
        'task': 'accounts.tasks_recurring.process_recurring_payments',
        'schedule': 3600.0,  # hourly — task only executes payments that are due
    },
}

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static'
MEDIA_ROOT = BASE_DIR / 'media'

# Auth
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'

# Session
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 48  # 48 hours

INTERNAL_IPS = ["127.0.0.1"]

DATE_FORMAT = "Y-m-d"
DATETIME_FORMAT = "Y-m-d H:i"

try:
    from boltpocket.local_settings import *
except ImportError:
    pass
