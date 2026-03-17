"""
Bolt Card LNURL-withdraw endpoints.

Flow:
1. POS reads NFC card → gets URL: lnurlw://server/boltcard/scan/<external_id>?p=...&c=...
2. POS calls the URL (GET) → server verifies tap, returns LnurlWithdrawResponse
3. POS creates invoice, calls callback with invoice → server pays it from wallet
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import BoltCard, BoltCardHit
from .nxp424 import verify_tap

import re

def _decode_invoice_amount(invoice):
    """
    Decode BOLT11 invoice amount. Tries local parsing first, falls back to Electrum RPC.
    Returns amount in sats (int) or None.
    """
    invoice = invoice.lower().strip()

    # Local BOLT11 amount decode
    # Format: ln(bc|tb|tbs)<amount><multiplier>1<data>
    for prefix in ('lnbc', 'lntbs', 'lntb'):
        if invoice.startswith(prefix):
            rest = invoice[len(prefix):]
            match = re.match(r'^(\d+)([munp]?)1', rest)
            if match:
                num = int(match.group(1))
                mult = match.group(2)
                if mult == 'm':
                    sats = num * 100000  # milli-BTC
                elif mult == 'u':
                    sats = num * 100  # micro-BTC
                elif mult == 'n':
                    sats = max(1, num // 10)  # nano-BTC
                elif mult == 'p':
                    sats = max(1, num // 10000)  # pico-BTC
                else:
                    sats = num * 100000000  # BTC
                return sats
            break

    # Fallback: try Electrum RPC
    try:
        from accounts.backends.electrum.client import electrum_command
        decoded = electrum_command('decode_invoice', {'invoice': invoice})
        amount_sats = decoded.get('amount_sat', 0)
        if not amount_sats:
            amount_msat = decoded.get('amount_msat', 0)
            amount_sats = amount_msat // 1000
        if amount_sats:
            return int(amount_sats)
    except Exception:
        pass

    return None

logger = logging.getLogger(__name__)


@require_GET
def lnurl_scan(request, external_id, card_secret):
    """
    Step 1: POS taps card, calls this URL.
    Verify the card tap, return LNURL-withdraw response.
    card_secret is part of the URL path — never stored in DB.
    """
    p = request.GET.get('p', '')
    c = request.GET.get('c', '')

    if not p or not c:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Missing p or c parameter',
        })

    # Some wallets send lowercase
    p = p.upper()
    c = c.upper()

    # Look up card by external_id
    try:
        card = BoltCard.objects.select_related('wallet__account').get(
            external_id=external_id
        )
    except BoltCard.DoesNotExist:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Card not found',
        })

    if not card.is_enabled:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Card is disabled',
        })

    # Verify card_secret
    if not card.verify_card_secret(card_secret):
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Invalid card secret',
        })

    # Decrypt keys using card_secret
    try:
        k0, k1, k2 = card.decrypt_keys(card_secret)
    except Exception:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Key decryption failed',
        })

    # Verify the tap (decrypt p, check CMAC c)
    success, counter_int, error, actual_uid = verify_tap(
        p_hex=p,
        c_hex=c,
        k1_hex=k1,
        k2_hex=k2,
        expected_uid_hex=card.uid,
    )

    if not success:
        return JsonResponse({
            'status': 'ERROR',
            'reason': error,
        })

    # First tap: store the real UID
    if card.uid == '00000000000000' and actual_uid:
        BoltCard.objects.filter(id=card.id).update(uid=actual_uid)
        logger.info(f'BoltCard {card.id} first tap — UID set to {actual_uid}')

    # Anti-replay: counter must strictly increase
    if counter_int <= card.counter:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Replay detected — counter not increasing',
        })

    old_counter = card.counter

    # Update counter
    BoltCard.objects.filter(id=card.id).update(counter=counter_int)

    # Check daily limit
    card.reset_daily_spent()
    if card.daily_limit > 0 and card.daily_spent >= card.daily_limit:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Daily limit reached',
        })

    # Get client info
    ip = request.META.get('HTTP_X_REAL_IP') or \
         request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or \
         request.META.get('REMOTE_ADDR')
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    # Create hit record
    hit = BoltCardHit.objects.create(
        card=card,
        ip=ip,
        user_agent=user_agent,
        old_counter=old_counter,
        new_counter=counter_int,
    )

    # Build callback URL
    callback = request.build_absolute_uri(f'/boltcard/callback/{hit.id}/')

    return JsonResponse({
        'tag': 'withdrawRequest',
        'callback': callback,
        'k1': str(hit.id),
        'defaultDescription': 'BoltCard payment',
        'minWithdrawable': 1000,           # 1 sat
        'maxWithdrawable': 1000000000,     # 1M sats — real limits enforced at callback
    })


@require_GET
def lnurl_callback(request, hit_id):
    """
    Step 2: POS sends invoice for payment.
    Verify and pay from the card's wallet account.
    """
    k1 = request.GET.get('k1', '')
    pr = request.GET.get('pr', '')

    if not k1 or not pr:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Missing k1 or pr parameter',
        })

    if str(k1) != str(hit_id):
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'k1 mismatch',
        })

    # Look up hit
    try:
        hit = BoltCardHit.objects.select_related('card__wallet__account').get(id=hit_id)
    except BoltCardHit.DoesNotExist:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Hit not found',
        })

    if hit.was_paid:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Already paid',
        })

    card = hit.card

    if not card.is_enabled:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Card is disabled',
        })

    # Decode the invoice to get the amount
    amount_sats = _decode_invoice_amount(pr)
    if amount_sats is None:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Failed to decode invoice amount',
        })

    if amount_sats <= 0:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Invoice has no amount',
        })

    # Check limits
    ok, reason = card.check_limits(amount_sats)
    if not ok:
        return JsonResponse({
            'status': 'ERROR',
            'reason': reason,
        })

    # Pay from the wallet's account
    account = card.wallet.account
    amount_btc = Decimal(amount_sats) / Decimal(10 ** 8)

    try:
        tx = account.send_to_destination(
            amount=amount_btc,
            destination=pr,
            card_verified=True,
        )
    except Exception as e:
        return JsonResponse({
            'status': 'ERROR',
            'reason': f'Payment failed: {e}',
        })

    # Record the spend
    card.record_spend(amount_sats)
    BoltCardHit.objects.filter(id=hit.id).update(
        amount_sats=amount_sats,
        was_paid=True,
    )

    logger.info(f'BoltCard {card.id} paid {amount_sats} sats via hit {hit.id}')

    return JsonResponse({'status': 'OK'})


@require_GET
def lnurl_auth(request):
    """
    Card provisioning endpoint.
    Called by the BoltCard NFC programmer app to get keys.
    """
    a = request.GET.get('a', '')

    if not a:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Missing auth parameter',
        }, status=400)

    # Look up card by OTP
    try:
        card = BoltCard.objects.get(otp=a)
    except BoltCard.DoesNotExist:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Card not found',
        }, status=404)

    # The auth endpoint needs the plaintext keys and card_secret.
    # These are passed via a one-time auth_data stored temporarily.
    # If auth_data is gone, the card has already been programmed.
    card_secret = request.GET.get('s', '')
    if not card_secret or not card.verify_card_secret(card_secret):
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Invalid or missing card secret',
        }, status=403)

    try:
        k0, k1, k2 = card.decrypt_keys(card_secret)
    except Exception:
        return JsonResponse({
            'status': 'ERROR',
            'reason': 'Key decryption failed',
        }, status=500)

    # Update UID if provided by programmer app (and card has placeholder)
    uid = request.GET.get('uid', '').upper().replace(':', '').replace(' ', '')
    if uid and len(uid) == 14 and card.uid == '00000000000000':
        BoltCard.objects.filter(id=card.id).update(uid=uid)
        logger.info(f'BoltCard {card.id} UID set to {uid}')

    # Generate new OTP (one-time use)
    import secrets
    new_otp = secrets.token_hex(16)
    BoltCard.objects.filter(id=card.id).update(otp=new_otp)

    # Build LNURL-withdraw base URL — includes card_secret
    lnurlw_base = request.build_absolute_uri(
        f'/boltcard/scan/{card.external_id}/{card_secret}'
    )
    lnurlw_base = lnurlw_base.replace('http://', 'lnurlw://').replace('https://', 'lnurlw://')

    return JsonResponse({
        'protocol_name': 'new_bolt_card_response',
        'protocol_version': '1',
        'card_name': uid or card.uid,
        'id': '1',
        'k0': k0,
        'k1': k1,
        'k2': k2,
        'k3': k1,  # K3 = K1 per spec
        'k4': k2,  # K4 = K2 per spec
        'lnurlw_base': lnurlw_base,
    })
