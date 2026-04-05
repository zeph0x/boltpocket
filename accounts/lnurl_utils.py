"""
Shared LNURL utilities: bech32 decoding, URL resolution.
Used by wallets/views.py (probe endpoint) and accounts/backends/electrum/ln_tasks.py (payment processing).
"""

import requests as http_requests


def decode_lnurl_bech32(lnurl_str):
    """Decode a bech32-encoded LNURL string to a URL."""
    lnurl_str = lnurl_str.lower()
    hrp, data = _bech32_decode(lnurl_str)
    if hrp != 'lnurl':
        raise ValueError(f'Expected lnurl HRP, got {hrp}')
    decoded = _convertbits(data, 5, 8, False)
    return bytes(decoded).decode('utf-8')


def resolve_lnurl_pay_url(destination):
    """
    Given an LN_ADDRESS destination (user@domain, lnurl1..., or lnurlp://...),
    return the LNURL-pay endpoint URL. Returns None if not resolvable.
    """
    d = destination.strip().lower()

    if d.startswith('lnurl1'):
        return decode_lnurl_bech32(d)
    elif d.startswith('lnurlp://'):
        return destination.strip().replace('lnurlp://', 'https://', 1)
    elif '@' in destination and '.' in destination.split('@')[-1]:
        local, domain = destination.strip().split('@', 1)
        return f'https://{domain}/.well-known/lnurlp/{local}'
    return None


def resolve_to_invoice(destination, amount_btc):
    """
    Resolve an LN_ADDRESS destination (user@domain, lnurl1..., lnurlp://...)
    to a BOLT11 invoice. Returns the invoice string.
    """
    url = resolve_lnurl_pay_url(destination)
    if not url:
        raise Exception(f'Cannot resolve LN address: {destination}')

    # Step 1: Fetch LNURL-pay metadata
    resp = http_requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get('status') == 'ERROR':
        raise Exception(f'LNURL error: {data.get("reason", "unknown")}')

    tag = data.get('tag')
    if tag != 'payRequest':
        raise Exception(f'Expected payRequest, got {tag}')

    callback = data.get('callback')
    if not callback:
        raise Exception('No callback in LNURL-pay response')

    # Step 2: Call callback with amount
    amount_msats = int(amount_btc * 100_000_000_000)  # BTC → millisats
    min_msats = data.get('minSendable', 0)
    max_msats = data.get('maxSendable', 0)
    if amount_msats < min_msats or (max_msats and amount_msats > max_msats):
        raise Exception(
            f'Amount {amount_msats} msat outside range [{min_msats}, {max_msats}]'
        )

    separator = '&' if '?' in callback else '?'
    invoice_url = f'{callback}{separator}amount={amount_msats}'
    resp = http_requests.get(invoice_url, timeout=10)
    resp.raise_for_status()
    invoice_data = resp.json()

    if invoice_data.get('status') == 'ERROR':
        raise Exception(f'LNURL callback error: {invoice_data.get("reason", "unknown")}')

    invoice = invoice_data.get('pr')
    if not invoice:
        raise Exception('No invoice returned from LNURL callback')

    return invoice


def _bech32_decode(bech):
    """Minimal bech32 decoder for LNURL."""
    CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    pos = bech.rfind('1')
    if pos < 1:
        raise ValueError('Invalid bech32')
    hrp = bech[:pos]
    data_part = bech[pos+1:]
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
