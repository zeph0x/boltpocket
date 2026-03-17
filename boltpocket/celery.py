import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'boltpocket.settings')

app = Celery('boltpocket')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Explicitly register tasks in nested modules
app.conf.include = [
    'accounts.backends.electrum.tasks',
    'accounts.backends.electrum.ln_tasks',
]


