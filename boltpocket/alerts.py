"""
Admin alerting module.
Sends alerts to Telegram and logs them.
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_admin_alert(message, level='warning'):
    """
    Send an alert to admin via Telegram and log it.

    Settings required:
        ADMIN_TELEGRAM_BOT_TOKEN = '...'
        ADMIN_TELEGRAM_CHAT_ID = '...'
    """
    # Always log
    log_fn = getattr(logger, level, logger.warning)
    log_fn(f'ADMIN ALERT: {message}')

    bot_token = getattr(settings, 'ADMIN_TELEGRAM_BOT_TOKEN', None)
    chat_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)

    if not bot_token or not chat_id:
        logger.debug('Telegram alert not configured, skipping.')
        return

    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        payload = {
            'chat_id': chat_id,
            'text': f'⚠️ BoltPocket Alert\n\n{message}',
            'parse_mode': 'HTML',
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f'Telegram alert failed: {resp.status_code} {resp.text}')
    except Exception as e:
        logger.error(f'Telegram alert exception: {e}')
