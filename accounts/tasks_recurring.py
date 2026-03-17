"""
Recurring payment processing.
Runs periodically via celery beat. Fires due payments through send_to_destination.
Supports both BTC-denominated and fiat-denominated recurring payments.
"""

import logging
import datetime
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Map currency code to Currency enum value
CURRENCY_MAP = {
    'USD': 1,
    'EUR': 2,
    'CHF': 3,
}


@shared_task
def process_recurring_payments():
    """
    Find all active recurring payments that are due and execute them.
    """
    from accounts.models import RecurringPayment

    now = timezone.now()
    due = RecurringPayment.objects.filter(
        is_active=True,
        deactivated_at=None,
        next_payment__lte=now,
    ).select_related('from_account')

    for rp in due:
        # Check end date
        if rp.end_date and now >= rp.end_date:
            rp.is_active = False
            rp.deactivated_at = now
            rp.save(update_fields=['is_active', 'deactivated_at'])
            logger.info(f'Recurring payment {rp.id} expired (end_date={rp.end_date})')
            continue

        try:
            _execute_recurring(rp, now)
        except Exception as e:
            logger.error(f'Recurring payment {rp.id} failed: {e}')
            rp.last_error = str(e)
            rp.save(update_fields=['last_error'])


def _execute_recurring(rp, now):
    """Execute a single recurring payment."""
    from accounts.models import RecurringPaymentExecution

    account = rp.from_account
    account.refresh_from_db()

    # Determine BTC amount
    if rp.is_fiat:
        amount_btc = _convert_fiat_to_btc(rp.amount_fiat, rp.amount_currency)
        if amount_btc is None:
            error = f'Price unavailable for {rp.amount_currency} — cannot convert'
            rp.last_error = error
            rp.save(update_fields=['last_error'])
            RecurringPaymentExecution.objects.create(
                recurring_payment=rp, status='failed', amount=Decimal(0),
                amount_fiat=rp.amount_fiat, amount_currency=rp.amount_currency, error=error,
            )
            logger.warning(f'Recurring payment {rp.id}: {error}')
            return
        logger.info(f'Recurring payment {rp.id}: {rp.amount_fiat} {rp.amount_currency} → {amount_btc} BTC')
    else:
        amount_btc = rp.amount

    balance = account.getbalance()
    if amount_btc > balance:
        amt_sats = int(amount_btc * 100_000_000)
        bal_sats = int(balance * 100_000_000)
        error = f'Insufficient balance: {bal_sats} sats available, need {amt_sats}'
        rp.last_error = error
        rp.save(update_fields=['last_error'])
        RecurringPaymentExecution.objects.create(
            recurring_payment=rp, status='failed', amount=amount_btc,
            amount_fiat=rp.amount_fiat if rp.is_fiat else None,
            amount_currency=rp.amount_currency if rp.is_fiat else '', error=error,
        )
        logger.warning(f'Recurring payment {rp.id}: {error}')
        return

    try:
        tx = account.send_to_destination(amount_btc, rp.destination)
        rp.last_payment = now
        rp.last_error = ''

        if rp.frequency == 'once':
            rp.is_active = False
            rp.deactivated_at = now
            rp.save(update_fields=['last_payment', 'last_error', 'is_active', 'deactivated_at'])
        else:
            rp.next_payment = rp.compute_next_payment()
            rp.save(update_fields=['last_payment', 'last_error', 'next_payment'])

        RecurringPaymentExecution.objects.create(
            recurring_payment=rp, status='success', amount=amount_btc,
            amount_fiat=rp.amount_fiat if rp.is_fiat else None,
            amount_currency=rp.amount_currency if rp.is_fiat else '',
            transaction=tx,
        )

        amt_sats = int(amount_btc * 100_000_000)
        logger.info(f'Recurring payment {rp.id}: sent {amt_sats} sats to {rp.destination}')
    except Exception as e:
        rp.last_error = str(e)
        rp.save(update_fields=['last_error'])
        RecurringPaymentExecution.objects.create(
            recurring_payment=rp, status='failed', amount=amount_btc,
            amount_fiat=rp.amount_fiat if rp.is_fiat else None,
            amount_currency=rp.amount_currency if rp.is_fiat else '', error=str(e),
        )
        raise


def _convert_fiat_to_btc(fiat_amount, currency_code):
    """Convert fiat amount to BTC using latest price. Returns Decimal or None."""
    from prices.tasks import get_latest_price

    currency_id = CURRENCY_MAP.get(currency_code)
    if not currency_id:
        return None

    price = get_latest_price(currency_id)
    if not price or price <= 0:
        return None

    # fiat_amount / price_per_btc = btc_amount
    btc_amount = (Decimal(str(fiat_amount)) / price).quantize(Decimal('0.00000001'))
    return btc_amount
