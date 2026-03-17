"""
LNURL-pay endpoints (LUD-06 + LUD-16 Lightning Address).

Lightning Address flow:
1. Payer wallet resolves user@domain → GET https://domain/.well-known/lnurlp/<user>
2. Server returns LNURL-pay metadata (min/max, description)
3. Payer wallet calls callback with amount
4. Server creates LN invoice via Electrum, tied to the wallet's account
5. Returns bolt11 invoice
6. Payer wallet pays it → check_ln_incoming credits the account
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.conf import settings

from .models import Wallet

logger = logging.getLogger(__name__)

# Limits in millisats
MIN_SENDABLE = 1_000        # 1 sat
MAX_SENDABLE = 1_000_000_000  # 1M sats


@require_GET
def lnurlp_metadata(request, address):
    """
    Step 1: /.well-known/lnurlp/<address>/
    Returns LNURL-pay metadata for the lightning address.
    """
    # Find wallet by lightning address
    wallet = None
    for w in Wallet.objects.filter(is_active=True).select_related('account'):
        if w.ln_address_local == address:
            wallet = w
            break

    if not wallet:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Address not found',
        }, status=404)

    domain = getattr(settings, 'LNURL_DOMAIN', request.get_host())
    ln_addr = wallet.ln_address(domain)

    metadata = json.dumps([
        ['text/plain', f'Payment to {ln_addr}'],
        ['text/identifier', ln_addr],
    ])

    callback = request.build_absolute_uri(f'/lnurlp/callback/{address}/')

    return JsonResponse({
        'tag': 'payRequest',
        'callback': callback,
        'minSendable': MIN_SENDABLE,
        'maxSendable': MAX_SENDABLE,
        'metadata': metadata,
        'commentAllowed': 0,
    })


@require_GET
def lnurlp_callback(request, address):
    """
    Step 2: /lnurlp/callback/<address>/?amount=<msats>
    Creates an invoice and returns it.
    """
    amount_str = request.GET.get('amount', '')

    if not amount_str:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Missing amount parameter',
        })

    try:
        amount_msats = int(amount_str)
    except ValueError:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Invalid amount',
        })

    if amount_msats < MIN_SENDABLE or amount_msats > MAX_SENDABLE:
        return JsonResponse({
            'status': 'ERROR',
            'reason': f'Amount out of range ({MIN_SENDABLE}-{MAX_SENDABLE} msats)',
        })

    # Find wallet
    wallet = None
    for w in Wallet.objects.filter(is_active=True).select_related('account'):
        if w.ln_address_local == address:
            wallet = w
            break

    if not wallet:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Address not found',
        })

    amount_sats = amount_msats // 1000
    amount_btc = Decimal(amount_sats) / Decimal(10 ** 8)

    # Build metadata hash for invoice description_hash (LUD-06 requirement)
    domain = getattr(settings, 'LNURL_DOMAIN', request.get_host())
    ln_addr = wallet.ln_address(domain)
    metadata = json.dumps([
        ['text/plain', f'Payment to {ln_addr}'],
        ['text/identifier', ln_addr],
    ])
    import hashlib
    description_hash = hashlib.sha256(metadata.encode()).hexdigest()

    # Create LN invoice via Electrum
    try:
        from accounts.backends.electrum.client import add_request
        result = add_request(str(amount_btc), memo=f'ln-address:{wallet.id}', expiry=600)
        bolt11 = result.get('lightning_invoice')
        payment_hash = result.get('rhash')

        if not bolt11:
            return JsonResponse({
                'status': 'ERROR',
                'reason': 'Failed to create invoice',
            })

        # Create DepositEndpoint so check_ln_incoming can credit the account
        from accounts.models import Asset, DepositEndpoint, EndpointType
        asset = Asset.objects.get(ticker='BTC')
        DepositEndpoint.objects.create(
            asset=asset,
            endpoint_type=EndpointType.LN,
            address=payment_hash,
            account=wallet.account,
        )

    except Exception as e:
        logger.error(f'LNURL-pay invoice creation failed: {e}')
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Invoice creation failed',
        })

    return JsonResponse({
        'pr': bolt11,
        'routes': [],
    })
