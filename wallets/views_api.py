"""
Lightweight read-only API for embedded devices (M5Stack, ESP32, etc).
Auth via access key in query parameter — no cookies/sessions needed.

Auth: pass SHA256(access_key) as the key parameter. Never send the raw access key.

Usage:
    GET /api/v1/balance/?key=SHA256(access_key)

    ESP32/M5Stack: compute SHA256 of the access key once, hardcode the hash.

    Returns:
    {
        "balance_sats": 9895,
        "balance_btc": "0.00009895",
        "price_chf": "82345.50",
        "value_chf": "8.15",
        "ln_address": "abc123@localhost",
        "wallet_id": 3
    }
"""

import hashlib
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Wallet


def _auth_by_key_value(key):
    """Authenticate wallet by client hash (SHA256 of access key)."""
    if not key:
        return None

    # key is the client_hash = SHA256(raw_access_key)
    # DB stores server_hash = SHA256(client_hash)
    server_hash = hashlib.sha256(key.encode()).hexdigest()

    try:
        return Wallet.objects.get(access_key_hash=server_hash, is_active=True)
    except Wallet.DoesNotExist:
        return None


@require_GET
def api_balance(request):
    """
    Return wallet balance + fiat prices. Lightweight for embedded devices.
    Single wallet:  GET /api/v1/balance/?key=<access_key>
    Multi wallet:   GET /api/v1/balance/?key=<key1>&key=<key2>&key=<key3>
    """
    keys = request.GET.getlist('key')
    if not keys:
        return JsonResponse({'error': 'Missing key parameter'}, status=401)

    from prices.tasks import get_latest_price
    from prices.models import Currency
    from django.conf import settings

    # Fetch prices once
    prices = {}
    for c in Currency:
        p = get_latest_price(c.value)
        if p:
            prices[c.name] = str(p)

    chf_price = get_latest_price(Currency.CHF.value)
    domain = getattr(settings, 'LNURL_DOMAIN', 'localhost')

    wallets = []
    for key in keys:
        wallet = _auth_by_key_value(key.strip())
        if not wallet:
            continue

        account = wallet.account
        balance = account.getbalance()
        balance_sats = int(balance * 100_000_000)
        chf_value = str((balance * chf_price).quantize(Decimal('0.01'))) if chf_price else None

        wallets.append({
            'balance_sats': balance_sats,
            'balance_btc': str(balance),
            'value_chf': chf_value,
            'ln_address': wallet.ln_address(domain),
        })

    if not wallets:
        return JsonResponse({'error': 'No valid wallets found'}, status=401)

    # Single key: flat response for simplicity on ESP32
    if len(wallets) == 1:
        result = wallets[0]
        result['prices'] = prices
        result['price_chf'] = prices.get('CHF')
        return JsonResponse(result)

    return JsonResponse({
        'wallets': wallets,
        'prices': prices,
    })
