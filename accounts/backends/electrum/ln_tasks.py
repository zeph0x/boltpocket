"""
Lightning Network payment processing via Electrum RPC.
Long-running Celery tasks with Redis locks — near-instant processing.
Celery beat restarts them every 60s if they die.

Safety principle: NEVER reverse a payment unless we're certain it failed.
When in doubt, flag for manual review.
"""

import logging
import time
import datetime
from decimal import Decimal

import redis
from celery import shared_task
from django.conf import settings

from accounts.backends.electrum.client import (
    lnpay, lightning_history, get_lightning_payment_status,
)

import hashlib
import json
import requests as http_requests

logger = logging.getLogger(__name__)

LOCK_TTL = 120


def _resolve_ln_address(otx):
    """
    Resolve an LN_ADDRESS destination (user@domain, lnurl1..., lnurlp://...)
    to a BOLT11 invoice via LNURL-pay.
    On success, updates the outgoing transaction destination to the invoice.
    """
    from accounts.models import Outgoingtransaction, DestinationType
    from accounts.lnurl_utils import resolve_to_invoice

    address = otx.destination.strip()
    invoice = resolve_to_invoice(address, otx.amount)

    # Verify invoice amount matches what we requested
    from wallets.views_boltcard import _decode_invoice_amount
    invoice_amount_sats = _decode_invoice_amount(invoice)
    expected_sats = int(otx.amount * 100_000_000)
    if invoice_amount_sats and invoice_amount_sats != expected_sats:
        raise Exception(
            f'Invoice amount mismatch: expected {expected_sats} sats, got {invoice_amount_sats} sats'
        )

    # Update outgoing tx with the resolved invoice
    Outgoingtransaction.objects.filter(id=otx.id).update(
        destination=invoice,
        destination_type=DestinationType.LN_INVOICE,
    )
    logger.info(f'LN address {address} resolved to invoice for outgoing tx {otx.id}')
POLL_INTERVAL = 1


def get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def acquire_lock(r, key):
    return r.set(key, '1', nx=True, ex=LOCK_TTL)


def release_lock(r, key):
    r.delete(key)


def refresh_lock(r, key):
    r.expire(key, LOCK_TTL)


# ---------------------------------------------------------------------------
# Outgoing LN payments
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=0, soft_time_limit=None, time_limit=None)
def process_ln_payments(self):
    """
    Long-running task: polls for pending outgoing LN payments every second.
    Redis lock prevents duplicate workers.
    """
    r = get_redis()
    lock_key = 'boltpocket:ln_payments:lock'

    if not acquire_lock(r, lock_key):
        return 'locked'

    try:
        while True:
            try:
                _process_pending_payments()
            except Exception as e:
                logger.error(f'LN payment processing error: {e}')

            refresh_lock(r, lock_key)
            time.sleep(POLL_INTERVAL)
    finally:
        release_lock(r, lock_key)


def _process_pending_payments():
    from accounts.models import (
        Outgoingtransaction, DestinationType, OutgoingStatus
    )

    # Resolve LN addresses to invoices first
    ln_address_pending = Outgoingtransaction.objects.filter(
        destination_type=DestinationType.LN_ADDRESS,
        status=OutgoingStatus.PENDING,
    )
    for otx in ln_address_pending:
        try:
            _resolve_ln_address(otx)
        except Exception as e:
            logger.error(f'LN address resolution {otx.id} error: {e}')
            _flag_for_review(otx, f'LN address resolution failed: {e}')

    # Pick up PENDING payments (invoices — including freshly resolved ones)
    pending = Outgoingtransaction.objects.filter(
        destination_type=DestinationType.LN_INVOICE,
        status=OutgoingStatus.PENDING,
    )

    for otx in pending:
        try:
            _attempt_ln_payment(otx)
        except Exception as e:
            logger.error(f'LN payment {otx.id} error: {e}')
            _flag_for_review(otx, f'Exception during payment: {e}')


def _attempt_ln_payment(otx):
    """
    Attempt to pay. Mark in_flight first, then call lnpay.
    On success: mark completed.
    On clear failure: verify with Electrum, then reverse only if confirmed failed.
    On ambiguous result: flag for review.
    """
    from accounts.models import Outgoingtransaction, OutgoingStatus

    # Mark in_flight BEFORE calling lnpay
    rows = Outgoingtransaction.objects.filter(
        id=otx.id, status=OutgoingStatus.PENDING
    ).update(status=OutgoingStatus.IN_FLIGHT)

    if rows != 1:
        return  # someone else picked it up

    # Calculate max fee: max(1% of amount, fee floor) — same as what we charged the user
    from accounts.models import Asset
    asset = Asset.objects.get(ticker='BTC')
    fee_btc = max(otx.amount * asset.ln_fee_percentage, asset.ln_fee_floor)
    max_fee_msat = int(fee_btc * 100_000_000_000)  # BTC → msat

    try:
        result = lnpay(otx.destination, max_fee_msat=max_fee_msat)
    except Exception as e:
        # RPC error — we don't know if payment was sent or not
        _flag_for_review(otx, f'RPC exception: {e}')
        return

    # Parse result
    success = False
    payment_hash = None
    preimage = None

    if isinstance(result, dict):
        success = result.get('success', False)
        payment_hash = result.get('payment_hash')
        preimage = result.get('preimage')
    elif result is True:
        success = True
    elif isinstance(result, str) and len(result) == 64:
        success = True
        payment_hash = result

    if success:
        _mark_completed(otx, payment_hash, preimage)
    elif isinstance(result, dict) and result.get('success') is False:
        # Electrum explicitly said failure — verify before reversing
        _verify_and_reverse(otx, payment_hash, f'Electrum reported failure: {result}')
    else:
        # Ambiguous — don't touch the balance
        _flag_for_review(otx, f'Ambiguous result: {result}')


def _mark_completed(otx, payment_hash, preimage):
    from accounts.models import Outgoingtransaction, OutgoingStatus

    Outgoingtransaction.objects.filter(id=otx.id).update(
        status=OutgoingStatus.COMPLETED,
        completed_at=datetime.datetime.now(),
        txid=payment_hash,
        payment_preimage=preimage,
    )
    logger.info(f'LN payment {otx.id} completed, hash: {payment_hash}')

    # Reconcile fees
    try:
        _reconcile_fee(otx, payment_hash)
    except Exception as e:
        logger.error(f'Fee reconciliation failed for payment {otx.id}: {e}')


def _flag_for_review(otx, reason):
    """Flag payment for manual review. Do NOT touch the balance."""
    from accounts.models import Outgoingtransaction, OutgoingStatus

    Outgoingtransaction.objects.filter(id=otx.id).update(
        status=OutgoingStatus.PENDING_REVIEW,
        review_reason=reason,
    )
    logger.warning(f'LN payment {otx.id} flagged for review: {reason}')

    from boltpocket.alerts import send_admin_alert
    send_admin_alert(
        f'LN payment <b>{otx.id}</b> flagged for review.\n'
        f'Amount: {otx.amount} BTC\n'
        f'Account: {otx.from_account_id}\n'
        f'Reason: {reason}'
    )


def _verify_and_reverse(otx, payment_hash, reason):
    """
    Double-check with Electrum that the payment truly failed before reversing.
    If verification is inconclusive, flag for review instead.
    """
    if payment_hash:
        status = get_lightning_payment_status(payment_hash)
        if status:
            # Payment exists in Electrum's history
            if status.get('preimage') or status.get('status') == 'settled':
                # Actually succeeded! Mark completed, don't reverse.
                _mark_completed(otx, payment_hash, status.get('preimage'))
                logger.warning(
                    f'LN payment {otx.id} reported failure but verification shows success!'
                )
                return
            elif status.get('status') not in ('failed', 'error'):
                # Not clearly failed — don't reverse
                _flag_for_review(otx, f'Verification inconclusive: {status}')
                return

    # Verified failed — safe to reverse
    _confirmed_reverse(otx, reason)


def _confirmed_reverse(otx, reason):
    """Reverse a payment that is CONFIRMED to have failed."""
    from accounts.models import (
        Account, AccountType, Outgoingtransaction, OutgoingStatus,
        Transaction, TxType
    )
    from django.db.models import F

    # Atomic: only reverse if still in a reversible state
    rows = Outgoingtransaction.objects.filter(
        id=otx.id,
        status__in=[OutgoingStatus.IN_FLIGHT, OutgoingStatus.PENDING_REVIEW],
    ).update(
        status=OutgoingStatus.FAILED,
        failed_at=datetime.datetime.now(),
        failed_reason=reason,
    )

    if rows != 1:
        logger.error(f'LN payment {otx.id} reversal skipped — status already changed')
        return

    account = otx.from_account
    ln_outgoing = Account.get_system_account(account.asset, AccountType.LN_OUTGOING)

    try:
        # Reverse amount: LN Outgoing -> User
        ln_outgoing.refresh_from_db()
        reversal_tx = ln_outgoing.send_to_account(account, otx.amount, TxType.LN_PAYMENT_REVERSAL)

        if not reversal_tx:
            raise Exception("LN outgoing reversal balance update failed")

        # Reverse fee: Fee -> User
        if otx.fee_charged and otx.fee_charged > 0:
            fee_account = Account.get_system_account(account.asset, AccountType.FEE)
            fee_account.refresh_from_db()
            fee_account.send_to_account(account, otx.fee_charged, TxType.FEE_REBATE)

        Outgoingtransaction.objects.filter(id=otx.id).update(
            reversal_transaction=reversal_tx,
        )

        logger.info(f'LN payment {otx.id} confirmed failed and reversed. Reason: {reason}')

    except Exception as e:
        logger.error(f'LN payment {otx.id} reversal failed: {e}')
        Outgoingtransaction.objects.filter(id=otx.id).update(
            status=OutgoingStatus.PENDING_REVIEW,
            review_reason=f'Reversal failed: {e}. Original reason: {reason}',
        )

        from boltpocket.alerts import send_admin_alert
        send_admin_alert(
            f'🚨 LN payment <b>{otx.id}</b> reversal FAILED.\n'
            f'Amount: {otx.amount} BTC\n'
            f'Account: {otx.from_account_id}\n'
            f'Balance update error — manual intervention needed.',
            level='error'
        )


# ---------------------------------------------------------------------------
# Fee reconciliation
# ---------------------------------------------------------------------------

def _reconcile_fee(otx, payment_hash):
    """
    After a successful LN payment, look up the actual fee paid and
    credit the difference (charged - actual) to the user's fee credit account.
    """
    from accounts.models import (
        Account, AccountType, Outgoingtransaction, Transaction, TxType
    )
    from django.db.models import F

    # Refresh from DB to get fee_charged
    otx = Outgoingtransaction.objects.get(id=otx.id)

    if otx.fee_charged is None or otx.fee_charged <= 0:
        return  # no fee was charged, nothing to reconcile

    if otx.fee_actual is not None:
        return  # already reconciled

    if not payment_hash:
        return

    # Look up actual fee from Electrum
    status = get_lightning_payment_status(payment_hash)
    if not status:
        logger.warning(f'Fee reconciliation: payment {payment_hash} not found in history')
        return

    fee_msat = status.get('fee_msat')
    if fee_msat is None:
        logger.warning(f'Fee reconciliation: no fee_msat for payment {payment_hash}')
        return

    actual_fee = Decimal(fee_msat) / Decimal(10 ** 11)  # msat -> BTC

    # Store actual fee
    Outgoingtransaction.objects.filter(id=otx.id).update(fee_actual=actual_fee)

    # Calculate rebate
    overpaid = otx.fee_charged - actual_fee
    if overpaid <= 0:
        return  # no rebate needed (shouldn't happen normally, but safe)

    # Credit the overpaid amount to user's fee credit account
    account = otx.from_account
    fee_account = Account.get_system_account(account.asset, AccountType.FEE)
    fee_credit_account = account.get_fee_credit_account()

    fee_account.refresh_from_db()
    tx = fee_account.send_to_account(fee_credit_account, overpaid, TxType.FEE_REBATE)
    if tx:
        logger.info(
            f'Fee rebate for payment {otx.id}: charged={otx.fee_charged} '
            f'actual={actual_fee} rebate={overpaid}'
        )


# ---------------------------------------------------------------------------
# Reconciliation — resolve stuck payments
# ---------------------------------------------------------------------------

@shared_task
def reconcile_ln_payments():
    """
    Periodic task: check IN_FLIGHT and PENDING_REVIEW payments against
    Electrum's payment history. Resolves stuck states.
    """
    from accounts.models import (
        Outgoingtransaction, DestinationType, OutgoingStatus
    )

    stuck = Outgoingtransaction.objects.filter(
        destination_type=DestinationType.LN_INVOICE,
        status__in=[OutgoingStatus.IN_FLIGHT, OutgoingStatus.PENDING_REVIEW],
    )

    for otx in stuck:
        try:
            _reconcile_payment(otx)
        except Exception as e:
            logger.error(f'Reconciliation error for payment {otx.id}: {e}')


def _reconcile_payment(otx):
    from accounts.models import OutgoingStatus

    payment_hash = otx.txid
    if not payment_hash:
        # No payment hash — if it's been stuck for > 10 min, likely never sent
        age_seconds = (datetime.datetime.now(datetime.timezone.utc) - otx.created_at).total_seconds()
        if age_seconds > 600 and otx.status == OutgoingStatus.IN_FLIGHT:
            _flag_for_review(otx, f'No payment hash after {int(age_seconds)}s — may not have been sent')
        return

    status = get_lightning_payment_status(payment_hash)

    if not status:
        # Not in Electrum history at all
        _flag_for_review(otx, 'Payment hash not found in Electrum history')
        return

    if status.get('preimage') or status.get('status') == 'settled':
        _mark_completed(otx, payment_hash, status.get('preimage'))
        logger.info(f'Reconciliation: payment {otx.id} confirmed successful')
    elif status.get('status') in ('failed', 'error'):
        _confirmed_reverse(otx, f'Reconciliation confirmed failure: {status}')
    else:
        # Still ambiguous — leave as is
        logger.debug(f'Reconciliation: payment {otx.id} still ambiguous: {status}')


# ---------------------------------------------------------------------------
# Incoming LN payments
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=0, soft_time_limit=None, time_limit=None)
def check_ln_incoming(self):
    """
    Long-running task: polls for settled incoming LN invoices every second.
    Redis lock prevents duplicate workers.
    """
    r = get_redis()
    lock_key = 'boltpocket:ln_incoming:lock'

    if not acquire_lock(r, lock_key):
        return 'locked'

    try:
        while True:
            try:
                _check_incoming()
            except Exception as e:
                logger.error(f'LN incoming check error: {e}')

            refresh_lock(r, lock_key)
            time.sleep(POLL_INTERVAL)
    finally:
        release_lock(r, lock_key)


def _check_incoming():
    """
    Scan Electrum lightning_history for incoming payments (direction=1).
    Match against DepositEndpoint records (endpoint_type=LN) by payment_hash.
    """
    from accounts.models import (
        Account, AccountType, Asset, DepositEndpoint, EndpointType,
        IncomingTransaction, Transaction, TxType
    )
    from django.db.models import F

    try:
        history = lightning_history()
    except Exception as e:
        logger.error(f'Failed to get lightning history: {e}')
        return

    if not history or not isinstance(history, list):
        return

    asset_btc = Asset.objects.filter(ticker='BTC').first()
    if not asset_btc:
        return

    for entry in history:
        # Only incoming payments
        if entry.get('direction') != 1:
            continue

        payment_hash = entry.get('payment_hash')
        if not payment_hash:
            continue

        # Already processed?
        tx_identifier = f'ln:{payment_hash}'
        if IncomingTransaction.objects.filter(tx_identifier=tx_identifier).exists():
            continue

        # Find matching DepositEndpoint
        try:
            endpoint = DepositEndpoint.objects.get(
                address=payment_hash,
                endpoint_type=EndpointType.LN,
                asset=asset_btc,
            )
        except DepositEndpoint.DoesNotExist:
            continue

        if not endpoint.account:
            logger.warning(f'LN endpoint {payment_hash} has no account, skipping')
            continue

        amount_msat = entry.get('amount_msat', 0)
        if not amount_msat or amount_msat <= 0:
            continue

        amount_btc = Decimal(amount_msat) / Decimal(10 ** 11)  # msat -> BTC
        account = endpoint.account

        ln_incoming = Account.get_system_account(asset_btc, AccountType.LN_INCOMING)
        ln_incoming.refresh_from_db()

        tx = ln_incoming.send_to_account(account, amount_btc, TxType.DEPOSIT)
        if tx:
            inc_tx = IncomingTransaction.objects.create(
                asset=asset_btc,
                address=endpoint,
                amount=amount_btc,
                confirmations=1,
                tx_identifier=tx_identifier,
                confirmed_at=datetime.datetime.now(),
                transaction=tx,
            )

            logger.info(f'LN deposit {payment_hash} credited to account {account.id}: {amount_btc} BTC')

            # Update endpoint
            DepositEndpoint.objects.filter(id=endpoint.id).update(
                first_used_at=datetime.datetime.now(),
                received=F('received') + amount_btc,
            )

            logger.info(f'LN deposit {payment_hash} credited to account {account.id}: {amount_btc} BTC')
        else:
            logger.error(f'LN deposit {payment_hash} balance update failed for account {account.id}')
