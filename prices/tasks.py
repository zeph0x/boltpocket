"""
BTC price feed via Kraken WebSocket.
Celery beat runs this every 60s. Redis lock ensures only one instance runs.
Writes latest price to Redis on each WS tick, snapshots to DB periodically.
"""

import json
import time
import logging
from decimal import Decimal

import redis
import websocket
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

REDIS_LOCK_KEY = 'boltpocket:price_feed:lock'
REDIS_PRICE_PREFIX = 'boltpocket:price:latest:'
LOCK_TTL = 120  # seconds — auto-expires if process crashes
SNAPSHOT_INTERVAL = 300  # write DB snapshot every 5 minutes
WS_URL = 'wss://ws.kraken.com'

# Kraken pair names mapped to our Currency enum
PAIRS = {
    'XBT/USD': 1,  # Currency.USD
    'XBT/EUR': 2,  # Currency.EUR
    'XBT/CHF': 3,  # Currency.CHF
}


def get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def acquire_lock(r):
    """Try to acquire Redis lock. Returns True if acquired."""
    return r.set(REDIS_LOCK_KEY, '1', nx=True, ex=LOCK_TTL)


def release_lock(r):
    r.delete(REDIS_LOCK_KEY)


def refresh_lock(r):
    r.expire(REDIS_LOCK_KEY, LOCK_TTL)


@shared_task(bind=True, max_retries=0)
def price_feed(self):
    """
    Connect to Kraken WS, stream prices.
    Celery beat calls this every 60s; lock prevents duplicates.
    """
    r = get_redis()

    if not acquire_lock(r):
        logger.debug('Price feed already running, skipping.')
        return 'locked'

    last_snapshot = {cid: 0.0 for cid in PAIRS.values()}

    try:
        ws = websocket.create_connection(WS_URL, timeout=30)

        subscribe_msg = json.dumps({
            'event': 'subscribe',
            'pair': list(PAIRS.keys()),
            'subscription': {'name': 'ticker'},
        })
        ws.send(subscribe_msg)

        # Map channel IDs to currency IDs from subscription responses
        channel_map = {}

        while True:
            try:
                raw = ws.recv()
                data = json.loads(raw)

                # Handle subscription status — map channelID to currency
                if isinstance(data, dict):
                    if data.get('event') == 'subscriptionStatus' and data.get('status') == 'subscribed':
                        pair = data.get('pair')
                        if pair in PAIRS:
                            channel_map[data['channelID']] = PAIRS[pair]
                    # heartbeat or other events
                    refresh_lock(r)
                    continue

                # Ticker data comes as [channelID, tickerData, "ticker", "XBT/USD"]
                if not isinstance(data, list) or len(data) < 4:
                    continue

                channel_id = data[0]
                ticker_data = data[1]
                currency_id = channel_map.get(channel_id)

                if currency_id is None:
                    continue

                # c = last trade closed [price, lot_volume]
                price_str = ticker_data.get('c', [None])[0]
                if not price_str:
                    continue

                price = Decimal(price_str)

                # Write latest to Redis (no expiry — stale price beats no price)
                r.set(
                    f'{REDIS_PRICE_PREFIX}{currency_id}',
                    str(price),
                )

                refresh_lock(r)

                # Periodic DB snapshot
                now = time.time()
                if now - last_snapshot[currency_id] >= SNAPSHOT_INTERVAL:
                    _write_snapshot(currency_id, price)
                    last_snapshot[currency_id] = now

            except websocket.WebSocketTimeoutException:
                refresh_lock(r)
                continue

    except Exception as e:
        logger.error(f'Price feed error: {e}')
    finally:
        release_lock(r)
        try:
            ws.close()
        except Exception:
            pass

    return 'disconnected'


def _write_snapshot(currency_id, price):
    """Write a price snapshot to the database."""
    from accounts.models import Asset
    from prices.models import PriceSnapshot

    try:
        asset = Asset.objects.filter(ticker='BTC').first()
        if not asset:
            return

        PriceSnapshot.objects.create(
            asset=asset,
            currency=currency_id,
            price=price,
            source='kraken',
            timestamp=timezone.now(),
        )
    except Exception as e:
        logger.error(f'Snapshot write error: {e}')


def get_latest_price(currency_id):
    """Read latest price from Redis. Returns Decimal or None."""
    r = get_redis()
    val = r.get(f'{REDIS_PRICE_PREFIX}{currency_id}')
    if val:
        return Decimal(val.decode())
    return None


def get_historical_price(currency_id, timestamp):
    """
    Get the BTC price closest to a given timestamp from PriceSnapshot.
    Looks for the nearest snapshot within 10 minutes. Returns Decimal or None.
    """
    from prices.models import PriceSnapshot
    from datetime import timedelta

    window = timedelta(minutes=10)

    # Try snapshot just before or at the timestamp
    snap = (
        PriceSnapshot.objects
        .filter(currency=currency_id, timestamp__gte=timestamp - window, timestamp__lte=timestamp + window)
        .order_by('timestamp')
        .first()
    )
    if snap:
        return snap.price
    return None
