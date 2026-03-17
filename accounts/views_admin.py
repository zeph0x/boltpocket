"""
Admin-only views: node stats, accounting overview.
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import Sum, Q, F, Count
from django.contrib.admin.views.decorators import staff_member_required

from accounts.backends.electrum.client import (
    electrum_wallet_command,
    electrum_command,
    getbalance,
)

logger = logging.getLogger(__name__)


@staff_member_required
def node_stats(request):
    """Admin dashboard showing Lightning + on-chain stats."""

    # --- Balances ---
    try:
        balance = getbalance()
    except Exception as e:
        balance = {'error': str(e)}

    onchain_confirmed = balance.get('confirmed', '0')
    onchain_unconfirmed = balance.get('unconfirmed', '0')
    lightning_balance = balance.get('lightning', '0')

    # --- Channels ---
    channels = []
    total_local = 0
    total_remote = 0
    total_capacity = 0
    try:
        raw_channels = electrum_wallet_command('list_channels')
        for ch in raw_channels:
            local = ch.get('local_balance', 0)
            remote = ch.get('remote_balance', 0)
            capacity = local + remote
            total_local += local
            total_remote += remote
            total_capacity += capacity

            channels.append({
                'short_id': ch.get('short_channel_id', '?'),
                'state': ch.get('state', '?'),
                'peer_state': ch.get('peer_state', '?'),
                'peer': ch.get('remote_pubkey', '?'),
                'local': local,
                'remote': remote,
                'capacity': capacity,
                'local_pct': round(local / capacity * 100) if capacity > 0 else 0,
                'remote_pct': round(remote / capacity * 100) if capacity > 0 else 0,
                'local_reserve': ch.get('local_reserve', 0),
                'remote_reserve': ch.get('remote_reserve', 0),
            })
    except Exception as e:
        logger.error(f'Failed to fetch channels: {e}')

    # --- Peers ---
    peers = []
    try:
        raw_peers = electrum_wallet_command('list_peers')
        for p in raw_peers:
            peers.append({
                'node_id': p.get('node_id', '?'),
                'initialized': p.get('initialized', False),
                'num_channels': len(p.get('channels', [])),
            })
    except Exception:
        pass

    # --- Node info ---
    node_info = {}
    try:
        info = electrum_command('getinfo')
        node_info = {
            'network': info.get('network', '?'),
            'server': info.get('server', '?'),
            'block_height': info.get('blockchain_height', '?'),
            'server_height': info.get('server_height', '?'),
            'connected': info.get('connected', False),
            'version': info.get('version', '?'),
        }
    except Exception:
        pass

    # --- Account stats ---
    from accounts.models import Account, Outgoingtransaction, OutgoingStatus
    from django.db.models import Count, Sum

    pending_payments = Outgoingtransaction.objects.filter(
        status__in=[OutgoingStatus.PENDING, OutgoingStatus.IN_FLIGHT]
    ).count()
    review_payments = Outgoingtransaction.objects.filter(
        status=OutgoingStatus.PENDING_REVIEW
    ).count()

    # --- Address pool ---
    from accounts.models import DepositEndpoint, EndpointType
    free_addresses = DepositEndpoint.objects.filter(
        account=None,
        endpoint_type=EndpointType.ONCHAIN,
    ).count()

    context = {
        'onchain_confirmed': onchain_confirmed,
        'onchain_unconfirmed': onchain_unconfirmed,
        'lightning_balance': lightning_balance,
        'channels': channels,
        'total_local': total_local,
        'total_remote': total_remote,
        'total_capacity': total_capacity,
        'total_local_pct': round(total_local / total_capacity * 100) if total_capacity > 0 else 0,
        'peers': peers,
        'node_info': node_info,
        'pending_payments': pending_payments,
        'review_payments': review_payments,
        'free_addresses': free_addresses,
    }

    # JSON API
    if request.GET.get('format') == 'json':
        return JsonResponse(context)

    return render(request, 'admin/node_stats.html', context)


@staff_member_required
def accounting(request):
    """Admin dashboard showing all accounting accounts, balances, and integrity checks."""
    from accounts.models import (
        Account, AccountType, Transaction, TxType,
        Outgoingtransaction, OutgoingStatus, RecurringPayment,
    )
    from wallets.models import Wallet

    # --- Account overview ---
    accounts = []
    total_balance = Decimal(0)
    total_computed = Decimal(0)
    has_mismatches = False

    for a in Account.objects.all().order_by('id'):
        inflow = Transaction.objects.filter(to_account=a).aggregate(s=Sum('amount'))['s'] or Decimal(0)
        outflow = Transaction.objects.filter(from_account=a).aggregate(s=Sum('amount'))['s'] or Decimal(0)
        computed = inflow - outflow
        balance_sats = int(a.balance * 100_000_000)
        computed_sats = int(computed * 100_000_000)
        diff = balance_sats - computed_sats
        total_balance += a.balance
        total_computed += computed

        # Find linked wallet
        wallet = None
        try:
            wallet = Wallet.objects.get(account=a)
        except Wallet.DoesNotExist:
            pass

        if diff != 0:
            has_mismatches = True

        accounts.append({
            'id': a.id,
            'type': a.get_account_type_display(),
            'account_type': a.account_type,
            'balance_sats': balance_sats,
            'computed_sats': computed_sats,
            'diff': diff,
            'inflow_sats': int(inflow * 100_000_000),
            'outflow_sats': int(outflow * 100_000_000),
            'wallet_id': wallet.id if wallet else None,
            'tx_count': Transaction.objects.filter(Q(from_account=a) | Q(to_account=a)).count(),
        })

    total_balance_sats = int(total_balance * 100_000_000)

    # --- Outgoing payment stats ---
    otx_stats = {}
    for status in OutgoingStatus:
        otx_stats[status.label] = Outgoingtransaction.objects.filter(status=status.value).count()

    # --- Recent outgoing with details ---
    recent_otx = []
    for otx in Outgoingtransaction.objects.order_by('-created_at')[:20]:
        charged = int(otx.fee_charged * 100_000_000) if otx.fee_charged else 0
        actual = int(otx.fee_actual * 100_000_000) if otx.fee_actual else None
        recent_otx.append({
            'id': otx.id,
            'from_account': otx.from_account_id,
            'amount_sats': int(otx.amount * 100_000_000),
            'dest_type': otx.get_destination_type_display(),
            'status': otx.get_status_display(),
            'fee_charged': charged,
            'fee_actual': actual,
            'fee_diff': charged - actual if actual is not None else None,
            'created': otx.created_at,
            'destination_short': (otx.destination or '')[:40] + '...' if otx.destination and len(otx.destination) > 40 else otx.destination,
        })

    # --- Transaction type breakdown ---
    tx_breakdown = []
    for tt in TxType:
        count = Transaction.objects.filter(tx_type=tt.value).count()
        total = Transaction.objects.filter(tx_type=tt.value).aggregate(s=Sum('amount'))['s'] or Decimal(0)
        if count > 0:
            tx_breakdown.append({
                'type': tt.label,
                'count': count,
                'total_sats': int(total * 100_000_000),
            })

    # --- Recurring payments ---
    recurring_active = RecurringPayment.objects.filter(is_active=True).count()
    recurring_errors = RecurringPayment.objects.filter(is_active=True).exclude(last_error='').count()

    context = {
        'accounts': accounts,
        'total_balance_sats': total_balance_sats,
        'has_mismatches': has_mismatches,
        'otx_stats': otx_stats,
        'recent_otx': recent_otx,
        'tx_breakdown': tx_breakdown,
        'recurring_active': recurring_active,
        'recurring_errors': recurring_errors,
    }

    if request.GET.get('format') == 'json':
        return JsonResponse(context, safe=False)

    return render(request, 'admin/accounting.html', context)


@staff_member_required
def generate_wallets(request):
    """
    Admin view to batch-generate wallets and download CSV.
    GET: show form. POST: create wallets, stream CSV download (never stored on disk).
    """
    if request.method == 'GET':
        return render(request, 'admin/generate_wallets.html')

    # POST — create wallets and stream CSV
    import csv
    import io
    from django.http import HttpResponse
    from django.conf import settings as django_settings
    from wallets.models import Wallet, SystemUser
    from accounts.models import Account, AccountType, Asset, TxType

    count = int(request.POST.get('count', 0))
    names_raw = request.POST.get('names', '')
    fund_sats = int(request.POST.get('fund', 0))

    if count < 1 or count > 100:
        return render(request, 'admin/generate_wallets.html', {'error': 'Count must be 1–100'})

    names = [n.strip() for n in names_raw.split(',') if n.strip()]
    while len(names) < count:
        names.append(f'Card {len(names) + 1}')
    names = names[:count]

    admin = request.user
    asset = Asset.objects.get(ticker='BTC')
    domain = getattr(django_settings, 'LNURL_DOMAIN', 'localhost')

    rows = []
    for i in range(count):
        account = Account.objects.create(
            asset=asset,
            account_type=AccountType.USER,
        )

        raw_key, client_hash, server_hash = Wallet.generate_access_key()
        wallet = Wallet.objects.create(
            creator=admin,
            account=account,
            access_key_hash=server_hash,
        )

        wallet_url = f'https://{domain}/wallet/#{raw_key}'
        ln_address = wallet.ln_address(domain)

        # Optional funding
        if fund_sats > 0:
            try:
                funding_account = Account.objects.get(id=1)
                funding_account.refresh_from_db()
                amount = Decimal(fund_sats) / Decimal(100_000_000)
                funding_account.send_to_account(account, amount, TxType.TRANSFER)
            except Exception:
                pass

        rows.append({
            'wallet_id': wallet.id,
            'account_id': account.id,
            'name': names[i],
            'wallet_url': wallet_url,
            'ln_address': ln_address,
            'access_key': raw_key,
            'api_key': client_hash,
        })

    # Stream CSV response — never touches disk
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="boltpocket_wallets_{count}x.csv"'

    writer = csv.DictWriter(response, fieldnames=['wallet_id', 'account_id', 'name', 'wallet_url', 'ln_address', 'access_key', 'api_key'])
    writer.writeheader()
    writer.writerows(rows)

    return response
