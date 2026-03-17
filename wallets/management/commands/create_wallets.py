"""
Batch wallet creation with CSV export for card printing.

Usage:
    python manage.py create_wallets --count 5 --names "Papa,Mama,Leo,Mia,Oma" --output cards.csv
    python manage.py create_wallets --count 3 --output cards.csv
    python manage.py create_wallets --count 1 --names "Leo" --fund 10000 --output cards.csv

Output CSV columns:
    wallet_id, account_id, name, wallet_url, ln_address, access_key
"""

import csv
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.conf import settings

from wallets.models import Wallet, SystemUser
from accounts.models import Account, AccountType, Asset


class Command(BaseCommand):
    help = 'Create wallets in batch and export CSV for card printing'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, required=True, help='Number of wallets to create')
        parser.add_argument('--names', type=str, default='', help='Comma-separated names (optional)')
        parser.add_argument('--output', type=str, default='cards.csv', help='Output CSV file path')
        parser.add_argument('--fund', type=int, default=0, help='Initial funding in sats (from account 1)')
        parser.add_argument('--domain', type=str, default='', help='Domain override for URLs')

    def handle(self, *args, **options):
        count = options['count']
        names = [n.strip() for n in options['names'].split(',') if n.strip()] if options['names'] else []
        output = options['output']
        fund_sats = options['fund']
        domain = options['domain'] or getattr(settings, 'LNURL_DOMAIN', 'localhost')

        # Pad names
        while len(names) < count:
            names.append(f'Card {len(names) + 1}')

        # Get admin user for wallet creation
        admin = SystemUser.objects.filter(is_admin=True).first()
        if not admin:
            self.stderr.write('No admin user found. Create one first.')
            return

        asset = Asset.objects.get(ticker='BTC')

        rows = []
        for i in range(count):
            name = names[i]

            # Create account (fee credit account is auto-created on first use)
            account = Account.objects.create(
                asset=asset,
                account_type=AccountType.USER,
            )

            # Generate access key
            raw_key, client_hash, server_hash = Wallet.generate_access_key()

            # Create wallet
            wallet = Wallet.objects.create(
                creator=admin,
                account=account,
                access_key_hash=server_hash,
            )

            wallet_url = f'https://{domain}/wallet/#{raw_key}'
            ln_address = wallet.ln_address(domain)

            # Optional funding
            if fund_sats > 0:
                funding_account = Account.objects.get(id=1)
                amount = Decimal(fund_sats) / Decimal(100_000_000)
                try:
                    from accounts.models import TxType
                    funding_account.refresh_from_db()
                    funding_account.send_to_account(account, amount, TxType.TRANSFER)
                    self.stdout.write(f'  Funded {name}: {fund_sats} sats')
                except Exception as e:
                    self.stderr.write(f'  Failed to fund {name}: {e}')

            rows.append({
                'wallet_id': wallet.id,
                'account_id': account.id,
                'name': name,
                'wallet_url': wallet_url,
                'ln_address': ln_address,
                'access_key': raw_key,
            })

            self.stdout.write(f'  Created wallet #{wallet.id} for {name}')

        # Write CSV
        with open(output, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['wallet_id', 'account_id', 'name', 'wallet_url', 'ln_address', 'access_key'])
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(f'\nCreated {count} wallets → {output}'))
        self.stdout.write(f'\nPreview:')
        for row in rows:
            self.stdout.write(f'  {row["name"]}: {row["ln_address"]}')
