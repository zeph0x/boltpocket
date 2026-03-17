import json
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Wallet, BoltCard


def wallet_login(request):
    """Serve the loader page. JS reads #fragment and authenticates."""
    return render(request, 'wallets/login.html')


@csrf_exempt
@require_POST
def wallet_auth(request):
    """Verify client hash, set wallet session."""
    try:
        data = json.loads(request.body)
        client_hash = data.get('key', '')
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'bad request'}, status=400)

    import hashlib
    server_hash = hashlib.sha256(client_hash.encode()).hexdigest()

    try:
        wallet = Wallet.objects.get(access_key_hash=server_hash, is_active=True)
    except Wallet.DoesNotExist:
        wallet = None

    if not wallet:
        return JsonResponse({'error': 'invalid key'}, status=403)

    request.session['wallet_id'] = wallet.id
    return JsonResponse({'ok': True})


def wallet_required(view_func):
    """Decorator: require authenticated wallet session."""
    def wrapper(request, *args, **kwargs):
        wallet_id = request.session.get('wallet_id')
        if not wallet_id:
            return redirect('/wallet/')
        try:
            request.wallet = Wallet.objects.get(id=wallet_id, is_active=True)
        except Wallet.DoesNotExist:
            del request.session['wallet_id']
            return redirect('/wallet/')
        return view_func(request, *args, **kwargs)
    return wrapper


@wallet_required
def wallet_dashboard(request):
    """Main wallet view — normal Django template."""
    from prices.tasks import get_latest_price
    from prices.models import Currency

    balance = request.wallet.account.getbalance()
    balance_sats = int(balance * 100_000_000)
    from decimal import Decimal

    # Fetch all fiat prices
    prices = {}
    for c in Currency:
        p = get_latest_price(c.value)
        if p:
            prices[c.name] = {
                'rate': p,
                'value': (balance * p).quantize(Decimal('0.01')),
            }

    # Format primary and secondary display values
    def format_currency(code):
        if code == 'BTC':
            return str(balance) + ' BTC'
        elif code == 'sats':
            return f'{balance_sats:,} sats'
        elif code in prices:
            return str(prices[code]['value']) + ' ' + code
        return None

    primary = request.wallet.primary_currency
    secondary = request.wallet.secondary_currency
    primary_display = format_currency(primary)
    secondary_display = format_currency(secondary)

    cards = BoltCard.objects.filter(wallet=request.wallet).order_by('-created_at')

    # Transaction history
    from accounts.models import Transaction
    from django.db.models import Q
    account = request.wallet.account
    transactions = Transaction.objects.filter(
        Q(from_account=account) | Q(to_account=account)
    ).order_by('-created_at')[:50]

    # Lightning address
    from django.conf import settings
    domain = getattr(settings, 'LNURL_DOMAIN', 'localhost')
    ln_address = request.wallet.ln_address(domain)

    # On-chain deposit address
    from accounts.models import DepositEndpoint, EndpointType
    onchain_address = ''
    try:
        endpoint = DepositEndpoint.objects.filter(
            account=account,
            endpoint_type=EndpointType.ONCHAIN,
        ).order_by('-created_at').first()
        if not endpoint:
            # Assign a new on-chain address from the pool
            endpoint = DepositEndpoint.objects.filter(
                account=None,
                endpoint_type=EndpointType.ONCHAIN,
                incomingtransaction=None,
            ).order_by('created_at').first()
            if endpoint:
                DepositEndpoint.objects.filter(id=endpoint.id, account=None).update(account_id=account.id)
                endpoint.refresh_from_db()
        if endpoint:
            onchain_address = endpoint.address
    except Exception:
        pass

    # Pending incoming transactions (unconfirmed or not yet credited)
    from accounts.models import IncomingTransaction
    incoming_endpoints = DepositEndpoint.objects.filter(account=account)
    incoming_pending = IncomingTransaction.objects.filter(
        address__in=incoming_endpoints,
        confirmed_at=None,
    ).order_by('-created_at')

    # Determine which fiat currency to use for conversions
    fiat_currency = primary if primary in ('USD', 'EUR', 'CHF') else (
        secondary if secondary in ('USD', 'EUR', 'CHF') else 'CHF'
    )

    # Preferred input unit: if primary is fiat, use that; else sats
    preferred_unit = primary if primary in ('USD', 'EUR', 'CHF') else 'sats'

    return render(request, 'wallets/dashboard.html', {
        'wallet': request.wallet,
        'balance': balance,
        'balance_sats': balance_sats,
        'primary_display': primary_display,
        'secondary_display': secondary_display,
        'fiat_currency': fiat_currency,
        'preferred_unit': preferred_unit,
        'cards': cards,
        'transactions': transactions,
        'incoming_pending': incoming_pending,
        'ln_address': ln_address,
        'onchain_address': onchain_address,
        'account': account,
        'display_currency_choices': Wallet.DISPLAY_CURRENCY_CHOICES,
        'fiat_currency_choices': Wallet.FIAT_CURRENCY_CHOICES,
    })


@csrf_exempt
@wallet_required
def wallet_probe_destination(request):
    """
    Probe a destination to determine type and amount constraints.
    Handles: LN invoices, LN addresses, LNURL-pay (lnurl1...), on-chain addresses.
    Returns: {type, min_sats, max_sats, fixed_amount, description}
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    destination = data.get('destination', '').strip()
    if not destination:
        return JsonResponse({'error': 'Destination required'}, status=400)

    d = destination.lower()

    # BOLT11 invoice
    if d.startswith('lnbc') or d.startswith('lntb') or d.startswith('lntbs'):
        from .views_boltcard import _decode_invoice_amount
        amount_sats = _decode_invoice_amount(destination)
        result = {'type': 'ln_invoice'}
        if amount_sats:
            result['fixed_sats'] = amount_sats
        return JsonResponse(result)

    # LNURL (bech32-encoded)
    lnurl_url = None
    if d.startswith('lnurl1'):
        try:
            lnurl_url = _decode_lnurl_bech32(d)
        except Exception:
            return JsonResponse({'error': 'Invalid LNURL'}, status=400)
    elif d.startswith('lnurlp://'):
        lnurl_url = destination.replace('lnurlp://', 'https://', 1)

    # Lightning address → LNURL-pay URL
    if not lnurl_url and '@' in destination and '.' in destination.split('@')[-1]:
        local, domain = destination.split('@', 1)
        lnurl_url = f'https://{domain}/.well-known/lnurlp/{local}'

    # Probe LNURL-pay endpoint
    if lnurl_url:
        try:
            import requests as http_requests
            resp = http_requests.get(lnurl_url, timeout=10)
            resp.raise_for_status()
            lnurl_data = resp.json()

            if lnurl_data.get('status') == 'ERROR':
                return JsonResponse({'error': f'LNURL error: {lnurl_data.get("reason", "unknown")}'}, status=400)

            tag = lnurl_data.get('tag')
            if tag != 'payRequest':
                return JsonResponse({'error': f'Unsupported LNURL tag: {tag}'}, status=400)

            min_msats = lnurl_data.get('minSendable', 0)
            max_msats = lnurl_data.get('maxSendable', 0)
            min_sats = (min_msats + 999) // 1000  # ceil
            max_sats = max_msats // 1000  # floor
            metadata = lnurl_data.get('metadata', '')
            callback = lnurl_data.get('callback', '')

            # Parse description from metadata JSON
            description = ''
            try:
                import json as json_mod
                meta_list = json_mod.loads(metadata)
                for entry in meta_list:
                    if entry[0] == 'text/plain':
                        description = entry[1]
                        break
            except Exception:
                pass

            result = {
                'type': 'lnurl_pay',
                'min_sats': min_sats,
                'max_sats': max_sats,
                'description': description,
                'callback': callback,
                'metadata': metadata,
            }
            if min_sats == max_sats:
                result['fixed_sats'] = min_sats

            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({'error': f'LNURL probe failed: {str(e)}'}, status=400)

    # On-chain address
    if d.startswith('bc1') or d.startswith('1') or d.startswith('3'):
        return JsonResponse({'type': 'onchain'})

    return JsonResponse({'error': 'Unrecognized destination'}, status=400)


def _decode_lnurl_bech32(lnurl_str):
    """Decode a bech32-encoded LNURL string to a URL."""
    lnurl_str = lnurl_str.lower()
    # Remove lnurl prefix and decode bech32
    hrp, data = _bech32_decode(lnurl_str)
    if hrp != 'lnurl':
        raise ValueError(f'Expected lnurl HRP, got {hrp}')
    # Convert 5-bit groups to 8-bit bytes
    decoded = _convertbits(data, 5, 8, False)
    return bytes(decoded).decode('utf-8')


def _bech32_decode(bech):
    """Minimal bech32 decoder for LNURL."""
    CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    pos = bech.rfind('1')
    if pos < 1:
        raise ValueError('Invalid bech32')
    hrp = bech[:pos]
    data_part = bech[pos+1:]
    # Decode characters to 5-bit values, strip 6-char checksum
    values = [CHARSET.index(c) for c in data_part]
    return hrp, values[:-6]


def _convertbits(data, frombits, tobits, pad=True):
    """General power-of-2 base conversion."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError('Invalid padding')
    return ret


def _resolve_lnurl_pay_invoice(callback, amount_sats, metadata=''):
    """
    Call LNURL-pay callback with amount to get a BOLT11 invoice.
    Returns (invoice_str, invoice_amount_sats).
    invoice_amount_sats is None if amount can't be decoded.
    """
    import requests as http_requests
    from .views_boltcard import _decode_invoice_amount

    amount_msats = amount_sats * 1000
    separator = '&' if '?' in callback else '?'
    url = f'{callback}{separator}amount={amount_msats}'

    resp = http_requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get('status') == 'ERROR':
        raise Exception(data.get('reason', 'unknown error'))

    invoice = data.get('pr')
    if not invoice:
        raise Exception('No invoice returned from LNURL callback')

    invoice_amount_sats = _decode_invoice_amount(invoice)
    return invoice, invoice_amount_sats


@csrf_exempt
@wallet_required
def wallet_send(request):
    """
    API endpoint to send a payment. Two-step:
    1. POST without p/c → validates and returns pending_id (payment not executed)
    2. POST with p/c (card tap) → verifies tap, executes payment
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Step 2: confirm a pending send with card tap
    pending_id = data.get('pending_id')
    if pending_id:
        return _confirm_send(request, data)

    # Step 1: validate and create pending send
    destination = data.get('destination', '').strip()
    if not destination:
        return JsonResponse({'error': 'Destination required'}, status=400)

    from accounts.models import Account, DestinationType
    from decimal import Decimal

    account = request.wallet.account

    # Resolve LNURL-pay (lnurl1...) to callback URL before detection
    d_lower = destination.lower()
    lnurl_callback = None
    lnurl_metadata = None
    if d_lower.startswith('lnurl1'):
        try:
            lnurl_url = _decode_lnurl_bech32(d_lower)
        except Exception:
            return JsonResponse({'error': 'Invalid LNURL'}, status=400)
        try:
            import requests as http_requests
            resp = http_requests.get(lnurl_url, timeout=10)
            resp.raise_for_status()
            lnurl_data = resp.json()
            if lnurl_data.get('tag') != 'payRequest':
                return JsonResponse({'error': f'Unsupported LNURL tag: {lnurl_data.get("tag")}'}, status=400)
            lnurl_callback = lnurl_data.get('callback')
            lnurl_metadata = lnurl_data.get('metadata', '')
        except Exception as e:
            return JsonResponse({'error': f'LNURL resolution failed: {str(e)}'}, status=400)

    dest_type = Account.detect_destination_type(destination)

    # Determine amount
    amount_sats = data.get('amount_sats')
    if dest_type == DestinationType.LN_INVOICE:
        if not amount_sats:
            from .views_boltcard import _decode_invoice_amount
            amount_sats = _decode_invoice_amount(destination)

        if not amount_sats:
            return JsonResponse({'error': 'Could not determine invoice amount'}, status=400)

    elif dest_type in (DestinationType.LN_ADDRESS, DestinationType.ONCHAIN):
        if not amount_sats or int(amount_sats) < 1:
            return JsonResponse({'error': 'Amount required'}, status=400)
        amount_sats = int(amount_sats)

    elif lnurl_callback:
        # LNURL-pay: amount required from user
        if not amount_sats or int(amount_sats) < 1:
            return JsonResponse({'error': 'Amount required'}, status=400)
        amount_sats = int(amount_sats)
        dest_type = DestinationType.LN_ADDRESS  # treat as LN for routing

    else:
        return JsonResponse({'error': 'Invalid destination'}, status=400)

    amount_btc = Decimal(amount_sats) / Decimal(100_000_000)

    # Check balance
    balance = account.getbalance()
    if amount_btc > balance:
        return JsonResponse({'error': f'Insufficient balance ({int(balance * 100_000_000)} sats available)'}, status=400)

    # Store pending send in session (expires with session, no DB needed)
    import secrets
    pending_id = secrets.token_hex(16)
    pending_data = {
        'destination': destination,
        'amount_sats': int(amount_sats),
        'dest_type': dest_type,
    }
    if lnurl_callback:
        pending_data['lnurl_callback'] = lnurl_callback
        pending_data['lnurl_metadata'] = lnurl_metadata
    request.session[f'pending_send_{pending_id}'] = pending_data

    return JsonResponse({
        'ok': True,
        'pending_id': pending_id,
        'amount_sats': int(amount_sats),
        'destination': destination,
        'message': 'Tap your bolt card to confirm.',
    })


def _confirm_send(request, data):
    """Verify card tap and execute a pending send."""
    from accounts.models import Account
    from decimal import Decimal

    pending_id = data.get('pending_id', '')
    p = data.get('p', '')
    c = data.get('c', '')

    if not p or not c:
        return JsonResponse({'error': 'Card tap required (missing p/c)'}, status=400)

    # Retrieve pending send from session
    session_key = f'pending_send_{pending_id}'
    pending = request.session.get(session_key)
    if not pending:
        return JsonResponse({'error': 'Pending payment expired or not found'}, status=400)

    # Look up card
    card_secret = data.get('card_secret', '')
    external_id = data.get('external_id', '')
    if not card_secret or not external_id:
        return JsonResponse({'error': 'Card identification required (external_id, card_secret)'}, status=400)

    try:
        card = BoltCard.objects.get(external_id=external_id, wallet=request.wallet, is_enabled=True)
    except BoltCard.DoesNotExist:
        return JsonResponse({'error': 'Card not found or not linked to this wallet'}, status=403)

    # Verify tap
    hit, error = card.authenticate_tap(card_secret, p, c)
    if error:
        return JsonResponse({'error': error}, status=403)

    # Execute the payment
    account = request.wallet.account
    amount_sats = pending['amount_sats']
    amount_btc = Decimal(amount_sats) / Decimal(100_000_000)
    destination = pending['destination']

    # Resolve LNURL-pay to invoice at payment time (avoids invoice expiry)
    if pending.get('lnurl_callback'):
        try:
            destination, invoice_amount_sats = _resolve_lnurl_pay_invoice(
                pending['lnurl_callback'], amount_sats, pending.get('lnurl_metadata', '')
            )
            # Verify invoice amount matches what user approved
            if invoice_amount_sats and invoice_amount_sats != amount_sats:
                del request.session[session_key]
                return JsonResponse({
                    'error': f'Invoice amount mismatch: expected {amount_sats} sats, got {invoice_amount_sats} sats'
                }, status=400)
        except Exception as e:
            return JsonResponse({'error': f'LNURL payment failed: {str(e)}'}, status=400)

    try:
        tx = account.send_to_destination(amount_btc, destination)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    # Clear pending
    del request.session[session_key]

    return JsonResponse({
        'ok': True,
        'message': f'Payment of {pending["amount_sats"]} sats sent!',
    })


@wallet_required
def wallet_recurring_list(request):
    """API: list recurring payments for this wallet."""
    from accounts.models import RecurringPayment
    account = request.wallet.account
    rps = RecurringPayment.objects.filter(from_account=account).order_by('-created_at')
    items = []
    for rp in rps:
        item = {
            'id': rp.id,
            'destination': rp.destination,
            'destination_type': rp.get_destination_type_display(),
            'amount_sats': int(rp.amount * 100_000_000),
            'frequency': rp.frequency,
            'description': rp.description,
            'is_active': rp.is_active,
            'is_fiat': rp.is_fiat,
            'next_payment': rp.next_payment.isoformat() if rp.next_payment else None,
            'last_payment': rp.last_payment.isoformat() if rp.last_payment else None,
            'last_error': rp.last_error,
            'end_date': rp.end_date.isoformat() if rp.end_date else None,
            'deactivated_at': rp.deactivated_at.isoformat() if rp.deactivated_at else None,
        }
        if rp.is_fiat:
            item['amount_fiat'] = str(rp.amount_fiat)
            item['amount_currency'] = rp.amount_currency
        items.append(item)
    return JsonResponse({'recurring': items})


@csrf_exempt
@wallet_required
def wallet_recurring_create(request):
    """
    API: create a recurring payment. Two-step:
    1. POST without p/c → validates, stores pending in session
    2. POST with pending_id + card tap → creates the recurring payment
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Step 2: confirm with card tap
    pending_id = data.get('pending_id')
    if pending_id:
        return _confirm_recurring(request, data)

    # Step 1: validate and store pending
    from accounts.models import Account, RecurringPayment, DestinationType
    from decimal import Decimal

    destination = data.get('destination', '').strip()
    amount_sats = data.get('amount_sats')
    amount_fiat = data.get('amount_fiat')
    currency = data.get('currency', '').strip()
    frequency = data.get('frequency', '').strip()
    description = data.get('description', '').strip()
    start_date_str = data.get('start_date', '').strip()
    end_date_str = data.get('end_date', '').strip()

    if not destination:
        return JsonResponse({'error': 'Destination required'}, status=400)

    dest_type = Account.detect_destination_type(destination)

    if dest_type == DestinationType.LN_INVOICE:
        return JsonResponse({'error': 'Invoices cannot be used for recurring payments (they expire). Use a lightning address instead.'}, status=400)

    valid_frequencies = [f.value for f in RecurringPayment.Frequency]
    if frequency not in valid_frequencies:
        return JsonResponse({'error': f'Invalid frequency. Use: {", ".join(valid_frequencies)}'}, status=400)

    valid_currencies = [c[0] for c in Wallet.FIAT_CURRENCY_CHOICES]

    is_fiat = bool(amount_fiat and currency)
    if is_fiat:
        if currency not in valid_currencies:
            return JsonResponse({'error': f'Invalid currency. Choose from: {", ".join(valid_currencies)}'}, status=400)
        try:
            fiat_val = float(amount_fiat)
        except Exception:
            return JsonResponse({'error': 'Invalid fiat amount'}, status=400)
        if fiat_val <= 0:
            return JsonResponse({'error': 'Amount must be positive'}, status=400)
    else:
        if not amount_sats or int(amount_sats) < 1:
            return JsonResponse({'error': 'Amount required'}, status=400)

    # Store pending in session
    import secrets
    pending_id = secrets.token_hex(16)
    request.session[f'pending_rp_{pending_id}'] = {
        'destination': destination,
        'dest_type': dest_type,
        'amount_sats': int(amount_sats) if not is_fiat else None,
        'amount_fiat': float(amount_fiat) if is_fiat else None,
        'currency': currency if is_fiat else '',
        'frequency': frequency,
        'description': description,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }

    if is_fiat:
        summary = f'{amount_fiat} {currency} {frequency}'
    else:
        summary = f'{int(amount_sats)} sats {frequency}'

    return JsonResponse({
        'ok': True,
        'pending_id': pending_id,
        'summary': summary,
        'destination': destination,
        'message': 'Tap your bolt card to confirm.',
    })


def _confirm_recurring(request, data):
    """Verify card tap and create a recurring payment."""
    from accounts.models import RecurringPayment, DestinationType
    from decimal import Decimal
    from django.utils import timezone
    import datetime

    pending_id = data.get('pending_id', '')
    p = data.get('p', '')
    c = data.get('c', '')

    if not p or not c:
        return JsonResponse({'error': 'Card tap required (missing p/c)'}, status=400)

    session_key = f'pending_rp_{pending_id}'
    pending = request.session.get(session_key)
    if not pending:
        return JsonResponse({'error': 'Pending recurring payment expired or not found'}, status=400)

    # Look up card
    card_secret = data.get('card_secret', '')
    external_id = data.get('external_id', '')
    if not card_secret or not external_id:
        return JsonResponse({'error': 'Card identification required'}, status=400)

    try:
        card = BoltCard.objects.get(external_id=external_id, wallet=request.wallet, is_enabled=True)
    except BoltCard.DoesNotExist:
        return JsonResponse({'error': 'Card not found or not linked to this wallet'}, status=403)

    # Verify tap
    hit, error = card.authenticate_tap(card_secret, p, c)
    if error:
        return JsonResponse({'error': error}, status=403)

    # Create the recurring payment
    account = request.wallet.account
    now = timezone.now()
    frequency = pending['frequency']

    # Parse first payment date
    start_date_str = pending.get('start_date', '')
    next_payment = None
    if start_date_str:
        try:
            next_payment = datetime.datetime.fromisoformat(start_date_str).replace(tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError):
            pass

    if not next_payment:
        next_payment = now

    # Reject dates in the past (before today)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_payment < today_start:
        return JsonResponse({'error': 'First payment date cannot be in the past'}, status=400)

    # Parse last payment date
    end_date = None
    end_date_str = pending.get('end_date', '')
    if end_date_str:
        try:
            end_date = datetime.datetime.fromisoformat(end_date_str).replace(tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError):
            pass

    is_fiat = bool(pending.get('amount_fiat') and pending.get('currency'))
    if is_fiat:
        amount_btc = Decimal('0')
        fiat_val = Decimal(str(pending['amount_fiat']))
        currency = pending['currency']
    else:
        amount_btc = Decimal(pending['amount_sats']) / Decimal(100_000_000)
        fiat_val = None
        currency = ''

    rp = RecurringPayment.objects.create(
        from_account=account,
        destination=pending['destination'],
        destination_type=pending['dest_type'],
        amount=amount_btc,
        amount_fiat=fiat_val,
        amount_currency=currency,
        frequency=frequency,
        description=pending.get('description', ''),
        next_payment=next_payment,
        end_date=end_date,
    )

    del request.session[session_key]

    # If first payment is due now or in the past, fire the task immediately
    from django.utils import timezone as tz
    if next_payment <= tz.now():
        from accounts.tasks_recurring import process_recurring_payments
        process_recurring_payments.delay()

    if is_fiat:
        msg = f'Recurring payment created: {fiat_val} {currency} {frequency} to {pending["destination"]}'
    else:
        msg = f'Recurring payment created: {pending["amount_sats"]} sats {frequency} to {pending["destination"]}'

    return JsonResponse({
        'ok': True,
        'id': rp.id,
        'message': msg,
    })


@wallet_required
def wallet_recurring_history(request, rp_id):
    """API: get execution history for a recurring payment."""
    from accounts.models import RecurringPayment, RecurringPaymentExecution

    rp = RecurringPayment.objects.filter(id=rp_id, from_account=request.wallet.account).first()
    if not rp:
        return JsonResponse({'error': 'Not found'}, status=404)

    executions = []
    for ex in rp.executions.order_by('-created_at')[:50]:
        executions.append({
            'id': ex.id,
            'created_at': ex.created_at.isoformat(),
            'status': ex.status,
            'amount_sats': int(ex.amount * 100_000_000),
            'amount_fiat': str(ex.amount_fiat) if ex.amount_fiat else None,
            'amount_currency': ex.amount_currency or None,
            'error': ex.error,
        })

    return JsonResponse({'executions': executions})


@csrf_exempt
@wallet_required
def wallet_recurring_toggle(request, rp_id):
    """API: activate/deactivate a recurring payment."""
    from accounts.models import RecurringPayment
    from django.utils import timezone

    rp = RecurringPayment.objects.filter(id=rp_id, from_account=request.wallet.account).first()
    if not rp:
        return JsonResponse({'error': 'Not found'}, status=404)

    if rp.is_active:
        rp.is_active = False
        rp.deactivated_at = timezone.now()
        rp.save(update_fields=['is_active', 'deactivated_at'])
        return JsonResponse({'ok': True, 'is_active': False, 'message': 'Recurring payment paused.'})
    else:
        rp.is_active = True
        rp.deactivated_at = None
        rp.save(update_fields=['is_active', 'deactivated_at'])
        return JsonResponse({'ok': True, 'is_active': True, 'message': 'Recurring payment resumed.'})


@csrf_exempt
@wallet_required
def wallet_recurring_delete(request, rp_id):
    """API: delete a recurring payment."""
    from accounts.models import RecurringPayment

    rp = RecurringPayment.objects.filter(id=rp_id, from_account=request.wallet.account).first()
    if not rp:
        return JsonResponse({'error': 'Not found'}, status=404)

    from django.utils import timezone
    rp.is_active = False
    rp.deactivated_at = timezone.now()
    rp.save(update_fields=['is_active', 'deactivated_at'])
    return JsonResponse({'ok': True, 'message': 'Recurring payment deleted.'})


@csrf_exempt
@wallet_required
def wallet_receive_invoice(request):
    """API: generate a BIP-21 unified payment request (on-chain + lightning)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    amount_sats = data.get('amount_sats')
    if not amount_sats or int(amount_sats) < 1:
        return JsonResponse({'error': 'Amount required'}, status=400)

    amount_sats = int(amount_sats)
    from decimal import Decimal
    amount_btc = Decimal(amount_sats) / Decimal(100_000_000)

    # Generate LN invoice via Electrum
    from accounts.backends.electrum.client import add_request
    try:
        result = add_request(
            amount_btc=float(amount_btc),
            memo=f'BoltPocket receive',
            expiry=3600,
            lightning=True,
        )
    except Exception as e:
        return JsonResponse({'error': f'Failed to create invoice: {e}'}, status=500)

    ln_invoice = result.get('lightning_invoice', '')
    rhash = result.get('rhash', '') or result.get('request_id', '')

    # Register LN deposit endpoint so check_ln_incoming credits the right account
    from accounts.models import DepositEndpoint, EndpointType, Asset
    account = request.wallet.account
    if rhash:
        asset = account.asset
        DepositEndpoint.objects.get_or_create(
            address=rhash,
            defaults={
                'asset': asset,
                'account': account,
                'endpoint_type': EndpointType.LN,
            },
        )

    # Get on-chain address
    account = request.wallet.account
    onchain = ''
    try:
        endpoint = DepositEndpoint.objects.filter(
            account=account,
            endpoint_type=EndpointType.ONCHAIN,
        ).order_by('-created_at').first()
        if endpoint:
            onchain = endpoint.address
    except Exception:
        pass

    # Build BIP-21 unified URI
    if onchain and ln_invoice:
        bip21 = f'bitcoin:{onchain}?amount={amount_btc}&lightning={ln_invoice}'
    elif ln_invoice:
        bip21 = ln_invoice
    elif onchain:
        bip21 = f'bitcoin:{onchain}?amount={amount_btc}'
    else:
        return JsonResponse({'error': 'No payment method available'}, status=500)

    return JsonResponse({
        'ok': True,
        'bip21': bip21,
        'lightning_invoice': ln_invoice,
        'onchain_address': onchain,
        'amount_sats': amount_sats,
        'amount_btc': str(amount_btc),
    })


@csrf_exempt
@wallet_required
def wallet_charge_card(request):
    """
    API: charge an external bolt card via LNURL-withdraw.
    Client sends us the card's tap URL (lnurlw://...) and our invoice.
    We call the card's LNURL endpoint to initiate the withdraw.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    card_url = data.get('card_url', '').strip()
    invoice = data.get('invoice', '').strip()

    if not card_url or not invoice:
        return JsonResponse({'error': 'card_url and invoice required'}, status=400)

    # Normalize URL scheme
    card_url = card_url.replace('lnurlw://', 'https://').replace('LNURLW://', 'https://')
    if not card_url.startswith('http'):
        card_url = 'https://' + card_url

    import requests as http_requests

    # Step 1: Call the card's LNURL-withdraw endpoint (GET)
    try:
        resp = http_requests.get(card_url, timeout=10, allow_redirects=True)
    except Exception as e:
        return JsonResponse({'error': f'Failed to reach card endpoint: {e}'}, status=502)

    try:
        lnurl_data = resp.json()
    except Exception:
        return JsonResponse({'error': f'Card endpoint returned non-JSON ({resp.status_code}): {resp.text[:200]}'}, status=502)

    if resp.status_code >= 400:
        reason = lnurl_data.get('reason') or lnurl_data.get('error') or lnurl_data.get('message') or resp.text[:200]
        return JsonResponse({'error': f'Card endpoint error ({resp.status_code}): {reason}'}, status=502)

    if lnurl_data.get('status') == 'ERROR':
        return JsonResponse({'error': f'Card error: {lnurl_data.get("reason", "unknown")}'}, status=400)

    if lnurl_data.get('tag') != 'withdrawRequest':
        return JsonResponse({'error': f'Not a withdraw endpoint (got tag: {lnurl_data.get("tag")})'}, status=400)

    callback = lnurl_data.get('callback', '')
    k1 = lnurl_data.get('k1', '')
    min_withdrawable = lnurl_data.get('minWithdrawable', 0)
    max_withdrawable = lnurl_data.get('maxWithdrawable', 0)

    if not callback or not k1:
        return JsonResponse({'error': 'Invalid LNURL-withdraw response (missing callback/k1)'}, status=400)

    # Step 2: Call the callback with our invoice
    from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

    parsed = urlparse(callback)
    existing_params = parse_qs(parsed.query)
    # Flatten: parse_qs returns lists, we want single values
    params = {k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()}
    params['k1'] = k1
    params['pr'] = invoice
    callback_url = urlunparse(parsed._replace(query=urlencode(params)))

    try:
        resp2 = http_requests.get(callback_url, timeout=15)
    except Exception as e:
        return JsonResponse({'error': f'Card callback failed: {e}'}, status=502)

    # Try to parse response regardless of status code
    try:
        result = resp2.json()
    except Exception:
        result = {}

    if resp2.status_code >= 400:
        reason = result.get('reason') or result.get('error') or result.get('message') or resp2.text[:200]
        return JsonResponse({'error': f'Card service error ({resp2.status_code}): {reason}'}, status=502)

    if result.get('status') == 'ERROR':
        return JsonResponse({'error': f'Payment rejected: {result.get("reason", "unknown")}'}, status=400)

    return JsonResponse({
        'ok': True,
        'message': 'Card charged! Payment is being processed.',
    })


@wallet_required
def wallet_price(request):
    """API: get current BTC price in all currencies + convert amounts."""
    from prices.tasks import get_latest_price
    from prices.models import Currency

    result = {}
    for c in Currency:
        p = get_latest_price(c.value)
        if p:
            result[c.name] = str(p)

    return JsonResponse({'prices': result})


@csrf_exempt
@wallet_required
def wallet_settings(request):
    """API: get or update wallet settings."""
    wallet = request.wallet

    if request.method == 'GET':
        return JsonResponse({
            'primary_currency': wallet.primary_currency,
            'secondary_currency': wallet.secondary_currency,
        })

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        valid = [c[0] for c in Wallet.DISPLAY_CURRENCY_CHOICES]

        primary = data.get('primary_currency')
        secondary = data.get('secondary_currency')

        if primary:
            if primary not in valid:
                return JsonResponse({'error': f'Invalid primary currency'}, status=400)
            wallet.primary_currency = primary

        if secondary:
            if secondary not in valid:
                return JsonResponse({'error': f'Invalid secondary currency'}, status=400)
            wallet.secondary_currency = secondary

        wallet.save(update_fields=['primary_currency', 'secondary_currency'])

        return JsonResponse({
            'ok': True,
            'message': 'Settings saved.',
        })

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
@wallet_required
def wallet_add_card(request):
    """
    API: create a new bolt card for this wallet.
    Returns provisioning QR data for the BoltCard programmer app.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    tx_limit = int(data.get('tx_limit', 0))
    daily_limit = int(data.get('daily_limit', 0))

    # Create card with placeholder UID (updated when card is first tapped)
    card, card_secret, k0, k1, k2 = BoltCard.create_card(
        wallet=request.wallet,
        uid='00000000000000',
        tx_limit=tx_limit,
        daily_limit=daily_limit,
    )

    # Build the auth URL for the BoltCard programmer app
    from django.conf import settings
    domain = getattr(settings, 'LNURL_DOMAIN', 'localhost')
    auth_url = f'https://{domain}/boltcard/auth/?a={card.otp}&s={card_secret}'

    return JsonResponse({
        'ok': True,
        'card_id': card.id,
        'auth_url': auth_url,
        'message': 'Scan the QR code with the BoltCard programmer app, then tap your NFC card.',
    })


@wallet_required
def boltcard_detail(request, card_id):
    """View bolt card info and recent taps (read-only)."""
    card = get_object_or_404(BoltCard, id=card_id, wallet=request.wallet)
    hits = card.hits.order_by('-created_at')[:20]

    return render(request, 'wallets/boltcard_detail.html', {
        'wallet': request.wallet,
        'card': card,
        'hits': hits,
    })
