"""
Simulate a bolt card tap to test the LNURL-withdraw flow end-to-end.
Run: cd /home/boltpocket && source venv/bin/activate && python test_boltcard.py
"""

import os
import sys
import json
import requests

os.environ['DJANGO_SETTINGS_MODULE'] = 'boltpocket.settings'

import django
django.setup()

from wallets.models import BoltCard, Wallet
from wallets.nxp424 import get_sun_mac
from Crypto.Cipher import AES


BASE_URL = 'http://100.71.118.92:8000'


def fake_sun(uid_hex, counter_int, k1_hex):
    """Generate fake p (encrypted SUN) as a real NTAG424 would."""
    uid = bytes.fromhex(uid_hex)
    counter = counter_int.to_bytes(3, 'little')

    # Build plaintext: 1 random byte + 7 uid + 3 counter + 5 padding
    plaintext = b'\x01' + uid + counter + b'\x00' * 5

    iv = b'\x00' * 16
    cipher = AES.new(bytes.fromhex(k1_hex), AES.MODE_CBC, iv)
    return cipher.encrypt(plaintext).hex().upper()


def fake_cmac(uid_hex, counter_int, k2_hex):
    """Generate fake c (CMAC) as a real NTAG424 would."""
    uid = bytes.fromhex(uid_hex)
    counter = counter_int.to_bytes(3, 'little')
    mac = get_sun_mac(uid, counter, bytes.fromhex(k2_hex))
    return mac.hex().upper()


def test():
    # Get the first wallet
    wallet = Wallet.objects.first()
    if not wallet:
        print('No wallet found. Create one first.')
        return

    print(f'Using wallet {wallet.id}')

    # Create a test card
    uid = '04AABBCCDDEE01'
    card, card_secret, k0, k1, k2 = BoltCard.create_card(
        wallet=wallet,
        card_name='Test Card',
        uid=uid,
        tx_limit=100000,   # 100k sats
        daily_limit=500000, # 500k sats
    )

    print(f'Created card {card.id}')
    print(f'  UID: {uid}')
    print(f'  External ID: {card.external_id}')
    print(f'  Card Secret: {card_secret}')
    print(f'  K1: {k1}')
    print(f'  K2: {k2}')
    print()

    # Simulate a tap (counter = 1)
    counter = 1
    p = fake_sun(uid, counter, k1)
    c = fake_cmac(uid, counter, k2)

    print(f'Simulated tap:')
    print(f'  p={p}')
    print(f'  c={c}')
    print()

    # Step 1: Call scan endpoint
    scan_url = f'{BASE_URL}/boltcard/scan/{card.external_id}/{card_secret}/?p={p}&c={c}'
    print(f'Step 1: GET {scan_url}')

    r = requests.get(scan_url)
    print(f'  Status: {r.status_code}')
    data = r.json()
    print(f'  Response: {json.dumps(data, indent=2)}')
    print()

    if data.get('status') == 'ERROR':
        print(f'FAILED: {data["reason"]}')
        return

    callback = data['callback']
    k1_token = data['k1']

    print(f'  Callback: {callback}')
    print(f'  k1: {k1_token}')
    print(f'  maxWithdrawable: {data["maxWithdrawable"]} msats')
    print()

    # Step 2: Create a test invoice and call callback
    # For now just test with a dummy invoice to verify the flow
    print('Step 2: To test payment, generate a real invoice and call:')
    print(f'  GET {callback}?k1={k1_token}&pr=<bolt11_invoice>')
    print()

    # Verify counter updated
    card.refresh_from_db()
    print(f'Card counter after tap: {card.counter} (expected: {counter})')
    print()

    # Try replay (should fail)
    print('Testing replay protection...')
    r2 = requests.get(scan_url)
    data2 = r2.json()
    print(f'  Replay result: {data2.get("status", "OK")} - {data2.get("reason", "no error")}')
    assert data2.get('status') == 'ERROR' and 'Replay' in data2.get('reason', ''), 'Replay protection FAILED!'
    print('  ✓ Replay correctly rejected')
    print()

    # Test with wrong card_secret
    print('Testing invalid card_secret...')
    bad_url = f'{BASE_URL}/boltcard/scan/{card.external_id}/badbadbadbadbadbadbadbadbadbadbad/?p={p}&c={c}'
    r3 = requests.get(bad_url)
    data3 = r3.json()
    print(f'  Bad secret result: {data3.get("status")} - {data3.get("reason")}')
    assert data3.get('status') == 'ERROR', 'Bad secret was accepted!'
    print('  ✓ Invalid secret correctly rejected')
    print()

    # Clean up
    from wallets.models import BoltCardHit
    BoltCardHit.objects.filter(card=card).delete()
    card.delete()
    print('Test card cleaned up.')
    print('ALL TESTS PASSED ✓')


if __name__ == '__main__':
    test()
