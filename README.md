# ⚡ BoltPocket

Self-hosted Bitcoin wallet with NFC card payments. Tap your card to pay at any boltcard supporting merchant.

The goal for the project is to allow anyone to host their own boltcard server, with straightforward and easy-to-use UX. Minimal configuration, minimal hassle, easy to use. Initially designed because I wanted to pay my kids allowance money in BTC, but I use it also for recurring donations and such.

## Features

- **NFC Bolt Cards** — tap-to-pay at any [BoltCard](https://boltcard.org)-compatible point of sale
- **Lightning Address** — receive sats at `you@your-domain.com`
- **Web Wallet** — send, receive, and manage funds from any browser
- **QR Code Scanner** — scan invoices, BIP-21 URIs, or lightning addresses to pay
- **Unified BIP-21 QR** — one QR code that works with both Lightning and on-chain wallets
- **Merchant Mode** — charge external bolt cards via NFC (LNURL-withdraw)
- **Recurring Payments** — schedule daily/weekly/monthly payments in sats or fiat
- **Fiat Conversion** — live BTC/USD/EUR/CHF prices, fiat-denominated recurring payments
- **Card Tap Auth** — every outgoing transaction requires a physical NFC card tap
- **Multi-Wallet** — create wallets for family members, each with their own card
- **E-ink Display** — M5Stack Paper S3 firmware shows wallet balances + weather
- **Admin Dashboard** — node stats, liquidity overview, accounting integrity checks
- **Double-Entry Accounting** — all balance movements through `send_to_account`

## Architecture

- **Backend**: Django + PostgreSQL + Celery + Redis
- **Lightning**: Electrum with Lightning Network support (JSON-RPC)
- **NFC**: NTAG 424 DNA cards with AES-128 encrypted keys ([BoltCard protocol](https://boltcard.org))
- **Frontend**: Vanilla HTML/CSS/JS (no framework, no build step)
- **Prices**: Kraken WebSocket feed

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL
- Redis
- Electrum with Lightning enabled (daemon mode with JSON-RPC)
- Nginx (reverse proxy, HTTPS)

### Installation

```bash
git clone https://github.com/your-org/boltpocket.git
cd boltpocket

# Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp boltpocket/local_settings.example.py boltpocket/local_settings.py
# Edit local_settings.py with your database, Electrum RPC, domain, etc.

# Database
python manage.py migrate
python manage.py createsuperuser

# Static files
python manage.py collectstatic

# Run
python manage.py runserver 0.0.0.0:8000
```

### Celery (background tasks)

```bash
celery -A boltpocket worker --beat -l info
```

Handles: Lightning payment processing, on-chain deposit detection, fee reconciliation, recurring payments (daily at 08:00 UTC), address pool refill.

### Electrum

```bash
electrum daemon -d
electrum load_wallet
electrum setconfig rpcuser boltpocket
electrum setconfig rpcpassword your-password
```

BoltPocket connects to Electrum via JSON-RPC for all Lightning and on-chain operations.

## NFC Cards

BoltPocket uses [NTAG 424 DNA](https://www.nxp.com/products/rfid-nfc/nfc-hf/ntag-424-dna) cards following the [BoltCard protocol](https://boltcard.org).

### Card Setup

1. Open a new wallet → setup screen appears
2. Click "Add Card" → set optional spending limits
3. Scan the QR code with the [BoltCard NFC programmer app](https://github.com/niccokunzmann/bolt-card-app) on Android
4. Tap your blank NTAG 424 DNA card to program it
5. Done — card is linked to the wallet

### Where to Buy Cards

- [shopnfc.com](https://www.shopnfc.com) — custom printed with variable data (QR codes, identicons)
- [nfc-tag-shop.de](https://www.nfc-tag-shop.de) — small quantities, custom printing

### Ordering Custom Cards

```bash
# 1. Generate wallets in admin → download CSV

# 2. Prepare print assets
cd scripts && npm install
node prepare_card_print.js wallets.csv --output-dir card_print/

# 3. Send to print shop:
#    - Background template (your design)
#    - print_data.csv (variable fields per card)
#    - identicons/ folder (unique icon per card)
```

## Wallet URL

Each wallet has a unique URL: `https://your-domain.com/wallet/#access-key`

The access key lives in the URL fragment (`#`) — never sent to the server. Authentication uses SHA-256 hash chain: client hashes the key, sends the hash, server verifies against stored double-hash.

Wallet URLs are bookmarkable — the page authenticates and loads inline.

## API

### Device API (M5Stack / ESP32)

```
GET /api/v1/balance/?key=SHA256(access_key)
```

Returns balance in sats, BTC, and fiat. Supports multiple wallets in one request:

```
GET /api/v1/balance/?key=hash1&key=hash2
```

### LNURL-pay (Lightning Address)

```
GET /.well-known/lnurlp/<address>/
```

Standard [LUD-16](https://github.com/lnurl/luds/blob/luds/16.md) implementation.

### LNURL-withdraw (Bolt Card)

```
GET /boltcard/scan/<external_id>/<card_secret>/?p=...&c=...
GET /boltcard/callback/<hit_id>/?k1=...&pr=...
```

Standard [BoltCard LNURL-withdraw](https://boltcard.org) implementation.

## M5Stack Paper S3 Display

The `firmware/` directory contains an Arduino sketch for the M5Stack Paper S3 e-ink display:

- Shows wallet balances + fiat values
- BTC/CHF price
- Weather info
- Updates hourly, deep sleeps between refreshes
- Button press triggers manual refresh

See `firmware/boltpocket_display/boltpocket_display.ino` for setup instructions.

## Admin

- `/admin/` — Django admin (wallets, cards, accounts, transactions)
- `/admin/node-stats/` — Lightning liquidity, channels, node info
- `/admin/accounting/` — Double-entry integrity checks, transaction breakdown
- `/admin/generate-wallets/` — Batch wallet creation with CSV download

## Security

- **Card tap required** for all outgoing transactions (send, recurring payment creation)
- **NFC keys encrypted** in database with AES-GCM, derived from card_secret (never stored)
- **Anti-replay** — strict counter increment on every card tap
- **Double-hash auth** — wallet access keys are SHA-256(SHA-256(key)), only hash stored
- **No plaintext secrets** — access keys shown once at creation, card_secret lives only on the NFC card

## Links

- [BoltCard Protocol](https://boltcard.org)
- [BoltCard NFC App](https://github.com/niccokunzmann/bolt-card-app)
- [NTAG 424 DNA Datasheet](https://www.nxp.com/docs/en/data-sheet/NT4H2421Gx.pdf)
- [BTC Map — Find Merchants](https://btcmap.org/map)
- [LNURL Spec](https://github.com/lnurl/luds)

## License

MIT
