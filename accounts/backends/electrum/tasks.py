import datetime
import logging
from django.db import models
from celery import shared_task
from decimal import Decimal

from accounts.backends.electrum.client import (
    electrum_wallet_command, electrum_command, getinfo as electrum_getinfo,
    create_new_address, paytomany, broadcast, get_tx_status, getbalance,
)

logger = logging.getLogger(__name__)


@shared_task
def electrum_refill_address_queue():
    from accounts.models import DepositEndpoint, EndpointType, Asset

    addresses_needed = 50
    asset_btc = Asset.objects.get(ticker="BTC")
    free_address_count = DepositEndpoint.objects.filter(
        account=None,
        asset=asset_btc,
        endpoint_type=EndpointType.ONCHAIN,
    ).count()
    created = 0
    for i in range(free_address_count, addresses_needed):
        address_string = create_new_address()

        if asset_btc.validate_address(address_string):
            DepositEndpoint.objects.create(
                address=address_string,
                account=None,
                asset=asset_btc,
                endpoint_type=EndpointType.ONCHAIN,
            )
            created += 1
        else:
            raise Exception(f"Invalid address returned from Electrum: {address_string}")

    if created:
        logger.info(f'Address pool: created {created} new on-chain addresses (pool now {free_address_count + created})')


@shared_task
def electrum_check_incoming_txs():
    from accounts.models import Account, Asset, DepositEndpoint, IncomingTransaction, Transaction, TxType

    asset_btc = Asset.objects.get(ticker="BTC")
    old_blockheight = asset_btc.blockheight

    result = electrum_wallet_command(
        "onchain_history", {"from_height": old_blockheight - 5}
    )
    # Handle both old format (dict with "transactions" key) and new format (list)
    if isinstance(result, dict):
        recent_transactions = result.get("transactions", [])
    elif isinstance(result, list):
        recent_transactions = result
    else:
        recent_transactions = []

    Asset.objects.filter(ticker="BTC").update(scan_started_at=datetime.datetime.now())

    for tx in recent_transactions:
        tx_id = tx["txid"]
        serialized_tx = electrum_command("gettransaction", [tx_id])
        txinfo = electrum_command("deserialize", [serialized_tx])["outputs"]
        vout = 0
        new_blockheight = max(tx["height"], old_blockheight)

        for i in txinfo:
            satoshi_amount_received = i["value_sats"]
            btc_amount = Decimal(satoshi_amount_received) / Decimal(10**8)
            TXidentifier = str(tx_id) + ":" + str(vout)
            txaddress = i["address"]

            if DepositEndpoint.objects.filter(address=txaddress, account__isnull=False).exists():
                incoming_address = DepositEndpoint.objects.get(address=txaddress)

                incoming_txs = IncomingTransaction.objects.filter(tx_identifier=TXidentifier)
                if incoming_txs.count() < 1:
                    inc_tx = IncomingTransaction.objects.create(
                        asset_id=1,
                        address=incoming_address,
                        amount=btc_amount,
                        confirmations=tx["confirmations"],
                        tx_identifier=TXidentifier,
                        transaction=None,
                    )
                else:
                    inc_tx = incoming_txs.first()

                if tx["confirmations"] >= 2 and inc_tx.transaction is None and inc_tx.confirmed_at is None:
                    accountid = incoming_address.account_id
                    account = Account.objects.get(id=accountid)

                    if account.balance != account.calculate_total_balance():
                        raise Exception("Balance mismatch, Account %d" % (account.id))

                    rows_updated_2 = IncomingTransaction.objects.filter(
                        id=inc_tx.id, tx_identifier=TXidentifier, confirmed_at=None
                    ).update(confirmed_at=datetime.datetime.now(), confirmations=tx["confirmations"])
                    if rows_updated_2 < 1:
                        raise Exception("Problem initiating tx, IncomingTransaction %d" % (inc_tx.id))

                    IncomingTransaction.objects.filter(
                        id=inc_tx.id, tx_identifier=TXidentifier
                    ).update(confirmations=tx["confirmations"])

                    from accounts.models import AccountType
                    incoming_account = Account.get_system_account(asset_btc, AccountType.ONCHAIN_INCOMING)
                    incoming_account.refresh_from_db()

                    txcreate = incoming_account.send_to_account(account, btc_amount, TxType.DEPOSIT)
                    if txcreate:
                        rows_updated_2 = IncomingTransaction.objects.filter(
                            tx_identifier=TXidentifier, transaction=None
                        ).update(transaction=txcreate)
                        if rows_updated_2 < 1:
                            raise Exception("Concurrency, IncomingTransaction %d update" % (inc_tx.id))
                    else:
                        logger.error("Balance update failed for account %d" % accountid)
                else:
                    logger.debug("DepositEndpoint not matched or not enough confirmations")
            else:
                logger.debug("Not our address: %s" % txaddress)
            vout += 1

    Asset.objects.filter(ticker="BTC").update(blockheight=new_blockheight)


@shared_task
def process_onchain_outgoing():
    """
    Process pending on-chain outgoing transactions.
    - PENDING: create + broadcast transaction via Electrum
    - IN_FLIGHT: check confirmation status
    """
    from accounts.models import (
        Account, AccountType, Asset, DestinationType,
        Outgoingtransaction, OutgoingStatus, Transaction, TxType,
    )
    from django.db.models import F

    from django.utils import timezone
    import datetime as dt

    asset_btc = Asset.objects.get(ticker='BTC')

    # All pending on-chain transactions
    pending = Outgoingtransaction.objects.filter(
        destination_type=DestinationType.ONCHAIN,
        status=OutgoingStatus.PENDING,
        asset=asset_btc,
    )

    has_urgent = pending.filter(is_urgent=True).exists()
    non_urgent_expired = pending.filter(
        is_urgent=False,
        created_at__lte=timezone.now() - dt.timedelta(hours=6),
    ).exists()

    # Send all pending as one batch if:
    # - any urgent tx exists, OR
    # - any non-urgent tx is older than 6 hours
    if has_urgent or non_urgent_expired:
        to_send = list(pending)
        if to_send:
            # Check on-chain balance before sending
            total_amount = sum(otx.amount for otx in to_send)
            try:
                balance_info = getbalance()
                onchain_confirmed = Decimal(balance_info.get('confirmed', '0'))
            except Exception as e:
                logger.error(f'On-chain batch: failed to check balance: {e}')
                return

            if total_amount > onchain_confirmed:
                logger.warning(
                    f'On-chain batch: insufficient on-chain balance. '
                    f'Need {total_amount} BTC, have {onchain_confirmed} BTC confirmed. '
                    f'{len(to_send)} transactions waiting. Will retry next cycle.'
                )
                return

            try:
                _send_onchain_batch(to_send)
            except Exception as e:
                logger.error(f'On-chain batch failed: {e}')
                for otx in to_send:
                    Outgoingtransaction.objects.filter(id=otx.id).update(
                        status=OutgoingStatus.PENDING_REVIEW,
                        review_reason=f'Batch send failed: {e}',
                    )

    # Check IN_FLIGHT transactions for confirmations
    in_flight = Outgoingtransaction.objects.filter(
        destination_type=DestinationType.ONCHAIN,
        status=OutgoingStatus.IN_FLIGHT,
        asset=asset_btc,
    )

    for otx in in_flight:
        try:
            _check_onchain_confirmation(otx)
        except Exception as e:
            logger.error(f'On-chain confirmation check {otx.id} failed: {e}')


def _send_onchain_batch(otx_list):
    """Batch multiple non-urgent on-chain transactions into a single paytomany call."""
    from accounts.models import Outgoingtransaction, OutgoingStatus

    ids = [otx.id for otx in otx_list]

    # Atomically mark all as in-flight
    rows = Outgoingtransaction.objects.filter(
        id__in=ids, status=OutgoingStatus.PENDING
    ).update(status=OutgoingStatus.IN_FLIGHT)

    if rows != len(ids):
        logger.warning(f'Batch: expected {len(ids)} rows, updated {rows}')
        # Re-fetch only the ones we actually locked
        otx_list = list(Outgoingtransaction.objects.filter(
            id__in=ids, status=OutgoingStatus.IN_FLIGHT
        ))
        if not otx_list:
            return

    try:
        outputs = [[otx.destination, str(otx.amount)] for otx in otx_list]
        tx_hex = paytomany(outputs)

        if isinstance(tx_hex, dict):
            tx_hex = tx_hex.get('hex', str(tx_hex))

        txid = broadcast(tx_hex)

        if isinstance(txid, dict):
            txid = txid.get('txid', str(txid))

        now = datetime.datetime.now()
        Outgoingtransaction.objects.filter(
            id__in=[otx.id for otx in otx_list]
        ).update(
            txid=txid,
            broadcasted_at=now,
            transaction_base64=tx_hex,
        )

        logger.info(f'On-chain batch ({len(otx_list)} txs) broadcast: txid={txid}')

    except Exception as e:
        Outgoingtransaction.objects.filter(
            id__in=[otx.id for otx in otx_list]
        ).update(
            status=OutgoingStatus.PENDING_REVIEW,
            review_reason=f'Batch broadcast failed: {e}',
        )
        logger.error(f'On-chain batch broadcast failed: {e}')


def _check_onchain_confirmation(otx):
    """Check if a broadcast on-chain transaction is confirmed."""
    from accounts.models import Outgoingtransaction, OutgoingStatus

    if not otx.txid:
        return

    try:
        status = get_tx_status(otx.txid)
    except Exception as e:
        logger.warning(f'On-chain {otx.id} status check failed: {e}')
        return

    confirmations = 0
    if isinstance(status, dict):
        confirmations = status.get('confirmations', 0) or 0
    elif isinstance(status, str) and 'confirmed' in status.lower():
        confirmations = 1

    if confirmations >= 1:
        Outgoingtransaction.objects.filter(id=otx.id).update(
            status=OutgoingStatus.COMPLETED,
            completed_at=datetime.datetime.now(),
        )
        logger.info(f'On-chain payment {otx.id} confirmed: txid={otx.txid}, confirmations={confirmations}')
