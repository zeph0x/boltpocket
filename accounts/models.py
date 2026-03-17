from django.db import models
from django.db.models import Sum

from django.db.models import F, Q
from decimal import Decimal
from django.conf import settings

class AccountType(models.IntegerChoices):
    USER = 1
    ONCHAIN_INCOMING = 10
    ONCHAIN_OUTGOING = 11
    LN_INCOMING = 20
    LN_OUTGOING = 21
    FEE = 30
    FEE_CREDIT = 31


class DestinationType(models.IntegerChoices):
    ONCHAIN = 1
    LN_INVOICE = 2
    LN_ADDRESS = 3
    INTERNAL = 4


class EndpointType(models.IntegerChoices):
    ONCHAIN = 1
    LN = 2


class TxType(models.IntegerChoices):
    DEPOSIT = 1
    WITHDRAW = 2
    TRANSFER = 3
    INTERNAL_FEE = 4
    ERROR_REVERSAL = 5
    CUSTODY_SERVICE_FEE = 6
    LN_PAYMENT_REVERSAL = 7
    FEE_REBATE = 8

class Asset(models.Model):
    """
    Description: Model Description
    """

    ticker = models.CharField(max_length=10, unique=True)
    atomic_unit = models.CharField(max_length=50)
    base_unit = models.CharField(max_length=50, default=None)

    description = models.TextField()

    # account where fees from transactions are credited
    blockchain_fee_account = models.ForeignKey('Account', on_delete=models.PROTECT, null=True, default=None, 
                                               related_name="fee_account_asset")

    custody_billing_account = models.ForeignKey('Account', on_delete=models.PROTECT, null=True, default=None, 
        related_name="custody_billing_account")

    # the fee for outgoing blockchain transactions
    outgoing_tx_fee_amount = models.DecimalField(max_digits=65, decimal_places=16, default=0.00005)

    # LN fee: fixed floor in BTC (e.g. 0.00000010 = 10 sats)
    ln_fee_floor = models.DecimalField(max_digits=65, decimal_places=16, default=Decimal('0.00000010'))
    # LN fee: percentage as decimal (e.g. 0.01 = 1%)
    ln_fee_percentage = models.DecimalField(max_digits=8, decimal_places=6, default=Decimal('0.01'))

    #Blockheight for checking purposes  
    blockheight = models.IntegerField(default=702398)

    #boolean for securing singular execution of tracing
    scan_started_at = models.DateTimeField(default=None, null=True)

    def validate_address(self, add):

        if self.ticker == "BTC":
            from CryptoAddressValidation.CryptoAddressValidation import Validation
            if Validation.is_address("BTC", add):
                return add
            else:
                return None
        elif self.ticker == "ETH":
            return None
        else:
            return None


    def __str__(self):
        return str(self.id) + " " + self.ticker + " " + self.description

    class Meta:
        pass

# ID, Ticker, unit, description
DEFAULT_ASSETS = (
    (1, 'BTC', 'btc', ''),
    (2, 'ETH', 'eth', ''),
)

def asset_identifier(asset_id):
    for ass in DEFAULT_ASSETS:
        if asset_id == ass[0]:
            return ass[1]
    raise Exception("asset_id %d not found" % (asset_id,))

def asset_unit(asset_id):
    for ass in DEFAULT_ASSETS:
        if asset_id == ass[0]:
            return ass[2]
    raise Exception("asset_id %d not found" % (asset_id,))

class Transaction(models.Model):
    """
    Transaction between accounts
    """
    
    created_at = models.DateTimeField(auto_now=False, auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    from_account = models.ForeignKey('Account', related_name="from_transactions", on_delete=models.PROTECT)
    to_account = models.ForeignKey('Account', related_name="to_transactions", on_delete=models.PROTECT)

    # in base unit, full BTC or some other asset
    amount = models.DecimalField(max_digits=65, decimal_places=16, null=False)

    incomingtx = models.ForeignKey("IncomingTransaction", null=True, on_delete=models.PROTECT, 
        verbose_name="Related incoming transaction", related_name="related_transactions")

    # balances before tx
    from_balance_before_tx = models.DecimalField(max_digits=65, decimal_places=16, null=True, default=None)
    to_balance_before_tx = models.DecimalField(max_digits=65, decimal_places=16, null=True, default=None)

    tx_type = models.IntegerField(choices=TxType.choices)

    # if internal transaction via address lookup, add foreign key to the assetaddress
    to_internal_address = models.ForeignKey('DepositEndpoint', null=True, default=None, on_delete=models.PROTECT)

    def from_balance_after_tx(self):
        return (self.from_balance_before_tx - self.amount).normalize()
    
    def to_balance_after_tx(self):
        return (self.to_balance_before_tx + self.amount).normalize()

    def get_account_balance_after_tx(self, account):
        if self.to_account == account:
            return self.to_balance_before_tx + self.amount
        elif self.from_account == account:
            return self.from_balance_before_tx - self.amount
        else:
            raise Exception("Account_id %s not related to this transaction" % (account,))

    def __str__(self):
        desc = ""
        if self.from_account_id and self.to_account_id:
            if self.to_internal_address_id:
                desc = "Internal from %d to %d, through %s" % (self.from_account_id, self.to_account_id, self.to_internal_address.address)
            else:
                desc = "Internal from %d to %d" % (self.from_account_id, self.to_account_id)
        elif self.from_account_id:
            desc = "Withdraw from %d" % (self.from_account_id)
        elif self.to_account_id:
            desc = "Deposit to %d" % (self.to_account_id)

        return "%s: %s, %s %s %s" % (asset_identifier(self.asset_id), self.created_at, 
            self.amount, asset_unit(self.asset_id), desc)

    class Meta:
        pass

class DepositEndpoint(models.Model):

    created_at = models.DateTimeField(auto_now=False, auto_now_add=True)
    first_used_at = models.DateTimeField(null=True, default=None)
    expired_at = models.DateTimeField(null=True, default=None)

    received = models.DecimalField(max_digits=65, decimal_places=16, default=0)

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    endpoint_type = models.IntegerField(choices=EndpointType.choices, default=EndpointType.ONCHAIN)

    # On-chain: BTC address. LN: payment_hash (hex).
    address = models.CharField(default="", unique=True, max_length=128, db_index=True)

    account = models.ForeignKey('Account', null=True, default=None, on_delete=models.PROTECT)


    def __str__(self):
        return "%s: %s, atomic unit received: %s" % (asset_identifier(self.asset_id), self.address, self.received)


class IncomingTransaction(models.Model):
    """
    Incoming transaction
    """
    
    created_at = models.DateTimeField(auto_now=False, auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, default=None)

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    address = models.ForeignKey('DepositEndpoint', on_delete=models.PROTECT)

    # Amount in BTC or some other asset
    amount = models.DecimalField(max_digits=65, decimal_places=16, null=False)

    confirmations = models.IntegerField(default=0)

    # unique identifier for transaction, for example for bitcoin txid:vout
    tx_identifier = models.CharField(max_length=500, unique=True)

    # once transaction is credited to account, transaction object is created and this is set.
    transaction = models.ForeignKey('Transaction', null=True, default=None, on_delete=models.PROTECT)

    def __str__(self):
        return "%s: %s %s %s To: %s..." % (asset_identifier(self.asset_id), self.tx_identifier, 
            self.amount, asset_unit(self.asset_id),
            self.address.address[:6])

    class Meta:
        pass


# Create your models here.

class Account(models.Model):
    """
    Account which has assets, transactions in and out and balance
    """
    
    created_at = models.DateTimeField(auto_now=False, auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    balance = models.DecimalField(max_digits=65, decimal_places=16, default=0)

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    account_type = models.IntegerField(choices=AccountType.choices, default=AccountType.USER)
    accounting_id = models.IntegerField(null=True, default=None, unique=True)
    allow_negative = models.BooleanField(default=False)

    # Direct link to this account's fee credit account (auto-created)
    fee_credit_account = models.OneToOneField('Account', on_delete=models.PROTECT, null=True, default=None,
        related_name="fee_credit_for")

    # some customers want charges to be separated to a separate billing account
    separate_fee_billing_account = models.ForeignKey('Account', on_delete=models.PROTECT, null=True, default=None, 
        related_name="fee_billing_account")
    # sometimes we want to have special fee for the account, this overrides the customer-specific fee
    custody_fee_percentage_per_month = models.DecimalField(null=True, default=None, decimal_places=8, max_digits=8)

    @staticmethod
    def get_system_account(asset, account_type):
        """Get or create a system account of the given type for the asset."""
        account, created = Account.objects.get_or_create(
            asset=asset,
            account_type=account_type,
            defaults={'allow_negative': True},
        )
        return account

    def get_fee_credit_account(self):
        """Get or create the fee credit account paired with this user account."""
        if self.account_type != AccountType.USER:
            raise Exception("Fee credit accounts are only for user accounts")
        if self.fee_credit_account_id:
            return self.fee_credit_account
        # Create fee credit account and link it
        fc = Account.objects.create(
            asset=self.asset,
            account_type=AccountType.FEE_CREDIT,
            allow_negative=False,
        )
        self.fee_credit_account = fc
        self.save(update_fields=['fee_credit_account'])
        return fc

    def calculate_ln_fee(self, amount):
        """Calculate the LN fee to charge for a given amount, minus any fee credit."""
        percentage_fee = amount * self.asset.ln_fee_percentage
        fixed_fee = max(percentage_fee, self.asset.ln_fee_floor)
        # Subtract available fee credit
        fee_credit_account = self.get_fee_credit_account()
        effective_fee = max(Decimal(0), fixed_fee - fee_credit_account.balance)
        credit_used = fixed_fee - effective_fee
        return fixed_fee, effective_fee, credit_used

    def find_unique_accounting_id(self, minimum_id):
        """
        Find unique accounting id for this account
        """
        if self.accounting_id != None:
            raise Exception("Accounting id already set")
        if minimum_id == None:
            minimum_id = 1
        # find unique accounting id
        for i in range(minimum_id, 1000000):
            if self.objects.filter(accounting_id=i).count() == 0:
                self.accounting_id = i
                self.save()
        raise Exception("Could not find unique accounting id")

    def get_incoming_in_timeframe(self, from_date, to_date):
        return (Transaction.objects.filter(to_account=self, created_at__range=[from_date, to_date]).aggregate(Sum('amount'))['amount__sum'] or Decimal(0)).normalize()

    def get_outcoming_in_timeframe(self, from_date, to_date):
        return (Transaction.objects.filter(from_account=self, created_at__range=[from_date, to_date]).aggregate(Sum('amount'))['amount__sum'] or Decimal(0)).normalize()

    def get_balance_before_date(self, from_date):
        latest_tx_before_date = Transaction.objects.filter(Q(from_account = self, created_at__lt = from_date) | Q(to_account = self, created_at__lt = from_date)).last()
        #if there is no tx before this date return 0
        if not latest_tx_before_date == None:
            #if to_account is self, it must be incoming tx so add the amount to balance before tx, otherwise substract from balance before tx
            if latest_tx_before_date.to_account == self:
                return (latest_tx_before_date.to_balance_before_tx + latest_tx_before_date.amount).normalize()
            else:
                return (latest_tx_before_date.from_balance_before_tx - latest_tx_before_date.amount).normalize()
        else:
            return Decimal(0)
    
    def max_balance_during_period(self, start_date, end_date):
        max_balance = self.get_balance_before_date(start_date)
        for tx in Transaction.objects.filter(Q(from_account = self, created_at__range = [start_date, end_date]) | Q(to_account = self, created_at__range = [start_date, end_date])).order_by('created_at'):
            if tx.to_account == self:
                max_balance = max(tx.to_balance_before_tx + tx.amount, max_balance)
            else:
                max_balance = max(tx.from_balance_before_tx - tx.amount, max_balance)
        return max_balance.normalize()

    def get_txlist_data_in_timeframe(self, from_date, to_date):
        txlist = []

        #fetch all tramsactions related to this account in date range
        txs = Transaction.objects.filter(Q(to_account=self, created_at__range=[from_date, to_date]) | Q(from_account=self, created_at__range=[from_date, to_date])).order_by("created_at")

        for i in txs:
            txlist.append(i)

        return txlist

    def getbalance(self):
        return self.balance.normalize()

    def getasset(self):
        return self.asset

    def calculate_total_balance(self):
        return ((self.to_transactions.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)) - \
            (self.from_transactions.aggregate(Sum('amount'))['amount__sum'] or Decimal(0))).normalize()

    def sendable_amount(self):
        return (self.balance + self.asset.outgoing_tx_fee_amount).normalize()

    @staticmethod
    def detect_destination_type(destination):
        """Detect destination type from string."""
        d = destination.lower().strip()
        if d.startswith('lnbc') or d.startswith('lntb') or d.startswith('lntbs'):
            return DestinationType.LN_INVOICE
        if d.startswith('lnurl1') or d.startswith('lnurlp://'):
            return DestinationType.LN_ADDRESS  # resolved to invoice at payment time
        if '@' in destination and '.' in destination.split('@')[-1]:
            return DestinationType.LN_ADDRESS
        return DestinationType.ONCHAIN

    @staticmethod
    def _extract_rhash_from_bolt11(invoice):
        """
        Extract the payment hash (rhash) from a BOLT11 invoice.
        The payment hash is the first tagged field (tag 'p', 52 data chars = 256 bits).
        Returns hex string or None.
        """
        try:
            invoice = invoice.lower().strip()
            # Find separator '1' — last occurrence splits HRP from data
            sep = invoice.rindex('1')
            data_part = invoice[sep + 1:-6]  # strip HRP and 6-char checksum

            # Bech32 charset
            CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
            # Convert to 5-bit values
            data5 = [CHARSET.index(c) for c in data_part]

            # Skip timestamp (first 7 x 5-bit = 35 bits)
            pos = 7

            # Read tagged fields
            while pos + 3 <= len(data5):
                tag = data5[pos]
                data_len = data5[pos + 1] * 32 + data5[pos + 2]
                pos += 3
                if pos + data_len > len(data5):
                    break

                if tag == 1:  # tag 'p' = payment hash (p is index 1 in CHARSET)
                    # Convert 5-bit groups to 8-bit bytes
                    bits = 0
                    acc = 0
                    result_bytes = []
                    for v in data5[pos:pos + data_len]:
                        acc = (acc << 5) | v
                        bits += 5
                        while bits >= 8:
                            bits -= 8
                            result_bytes.append((acc >> bits) & 0xFF)
                    return bytes(result_bytes[:32]).hex()

                pos += data_len
        except Exception:
            pass
        return None

    def send_to_destination(self, amount, destination, urgent=True):
        # Normalize: LN invoices are case-insensitive, lowercase is canonical
        destination = destination.strip()
        d_lower = destination.lower()
        if d_lower.startswith('lnbc') or d_lower.startswith('lntb'):
            destination = d_lower
        if amount <= 0:
            raise Exception("Account %d wrong amount %s %s" %
                (self.id, amount, self.asset.base_unit))

        dest_type = Account.detect_destination_type(destination)

        # Calculate fees based on destination type
        if dest_type == DestinationType.ONCHAIN:
            if self.balance < amount + self.asset.outgoing_tx_fee_amount:
                raise Exception("Account %d insufficient balance to send %s %s" %
                    (self.id, amount, self.asset.base_unit))
        elif dest_type in (DestinationType.LN_INVOICE, DestinationType.LN_ADDRESS):
            fixed_fee, effective_fee, credit_used = self.calculate_ln_fee(amount)
            if self.balance < amount + effective_fee:
                raise Exception("Account %d insufficient balance to send %s %s (need %s + %s fee)" %
                    (self.id, amount, self.asset.base_unit, amount, effective_fee))
        else:
            if self.balance < amount:
                raise Exception("Account %d insufficient balance to send %s %s" %
                    (self.id, amount, self.asset.base_unit))

        # Extra check that we aren't having wrong balance in database
        sendable_balance_db = self.calculate_total_balance()
        if self.balance != sendable_balance_db:
            raise Exception("Account %d balance mismatch, in cache %s, should be %s" %
                (self.id, self.balance, sendable_balance_db))

        # Check for internal transfers (on-chain address or LN invoice with known rhash)
        internal_endpoint = None
        if dest_type == DestinationType.ONCHAIN:
            if not self.asset.validate_address(destination):
                raise Exception("Address not valid " + str(destination))
            internal_endpoint = DepositEndpoint.objects.filter(address=destination, asset=self.asset).first()

        elif dest_type == DestinationType.LN_INVOICE:
            rhash = self._extract_rhash_from_bolt11(destination)
            if rhash:
                internal_endpoint = DepositEndpoint.objects.filter(
                    address=rhash, asset=self.asset, endpoint_type=EndpointType.LN,
                ).first()

        if internal_endpoint and internal_endpoint.account:
            if internal_endpoint.account.id == self.id:
                raise Exception("Cannot send to yourself")
            # Internal transfer — use send_to_account
            return self.send_to_account(internal_endpoint.account, amount, TxType.TRANSFER)

        # External payment — deduct balance and create outgoing transaction
        if dest_type in (DestinationType.LN_INVOICE, DestinationType.LN_ADDRESS):
            outgoing_account = Account.get_system_account(self.asset, AccountType.LN_OUTGOING)
        else:
            outgoing_account = Account.get_system_account(self.asset, AccountType.ONCHAIN_OUTGOING)

        tx = self.send_to_account(outgoing_account, amount, TxType.WITHDRAW)
        if not tx:
            raise Exception("Account %d balance not updated" % self.id)

        otx = Outgoingtransaction.objects.create(
            from_account=self,
            destination=destination,
            destination_type=dest_type,
            transaction=tx,
            amount=amount,
            asset=self.asset,
            is_urgent=urgent)

        # On-chain fee handling
        if dest_type == DestinationType.ONCHAIN:
            fee_account = self.asset.blockchain_fee_account
            fee_tx = self.send_to_account(fee_account, self.asset.outgoing_tx_fee_amount, TxType.INTERNAL_FEE)
            if not fee_tx:
                raise Exception("Account %d fee balance not updated" % self.id)
            # Trigger immediate processing for urgent on-chain txs
            if urgent:
                from accounts.backends.electrum.tasks import process_onchain_outgoing
                process_onchain_outgoing.delay()

        # LN fee handling
        elif dest_type in (DestinationType.LN_INVOICE, DestinationType.LN_ADDRESS):
            fee_account = Account.get_system_account(self.asset, AccountType.FEE)
            fee_credit_account = self.get_fee_credit_account()

            # Drain fee credit first if available
            if credit_used > 0:
                fee_credit_account.refresh_from_db()
                credit_tx = fee_credit_account.send_to_account(fee_account, credit_used, TxType.INTERNAL_FEE)
                if not credit_tx:
                    raise Exception("Fee credit balance not updated for account %d" % self.id)

            # Charge remaining fee from user account
            if effective_fee > 0:
                self.refresh_from_db()
                fee_tx = self.send_to_account(fee_account, effective_fee, TxType.INTERNAL_FEE)
                if not fee_tx:
                    raise Exception("Account %d fee balance not updated" % self.id)

            # Store the charged fee on the outgoing tx for reconciliation
            Outgoingtransaction.objects.filter(id=otx.id).update(
                fee_charged=fixed_fee
            )

        return tx

    def send_to_account(self, other_account, amount, txtype):
        if other_account.asset_id != self.asset_id:
            raise Exception("Mismatching assets")
        if amount <= 0:
            raise Exception("Can't send negative amount")
        if not self.allow_negative:
            if amount > self.balance:
                raise Exception("not enough balance")
            sendable_balance = self.calculate_total_balance()
            if amount > sendable_balance:
                raise Exception("not enough balance")

        new_balance = self.balance - amount
        rows_updated = Account.objects.filter(id=self.id, balance=self.balance).update(balance=new_balance)
        if rows_updated == 1:
            self.balance = new_balance
            tx = Transaction.objects.create(asset= self.asset, from_account=self, to_account=other_account, amount=amount, tx_type=txtype, from_balance_before_tx=new_balance + amount, to_balance_before_tx= other_account.balance)
            rows_updated_2 = Account.objects.filter(id=other_account.id).update(balance=F('balance') + amount)
            if rows_updated_2 < 1:
                import logging
                logging.getLogger(__name__).error(
                    f'send_to_account: target account {other_account.id} balance not updated. '
                    f'Source account {self.id}, amount {amount}'
                )
                from boltpocket.alerts import send_admin_alert
                send_admin_alert(
                    f'send_to_account target account <b>{other_account.id}</b> balance not updated.\n'
                    f'Source: {self.id}, Amount: {amount} BTC',
                    level='error'
                )
            return tx

        elif rows_updated > 1:
            raise Exception("multiple rows were updated")

    def get_new_address(self):
        address = DepositEndpoint.objects.filter(asset=self.asset, account=None, incomingtransaction=None).order_by('created_at').first()
        if not address:
            # Pool empty — generate on the fly
            from accounts.backends.electrum.client import create_new_address
            new_addr = create_new_address()
            address = DepositEndpoint.objects.create(
                asset=self.asset,
                account=self,
                address=new_addr,
                endpoint_type=EndpointType.ONCHAIN,
            )
            return address
        rows_updated = DepositEndpoint.objects.filter(id=address.id, account=None).update(account_id=self.id)
        if rows_updated == 1:
            return address

    def get_unused_address(self):
        address = DepositEndpoint.objects.filter(asset_id=self.asset, account_id=self.id, incomingtransaction=None, first_used_at=None).order_by('created_at').first()
        if not address:
            return self.get_new_address()
        return address

    def __str__(self):
        return "%s Account %d, balance %s" % (asset_identifier(self.asset_id), self.id, self.balance)

    class Meta:
        pass

class OutgoingStatus(models.IntegerChoices):
    PENDING = 1          # created, waiting for pickup
    IN_FLIGHT = 2        # payment attempt in progress
    COMPLETED = 3        # confirmed success
    FAILED = 4           # confirmed failure, balance reversed
    PENDING_REVIEW = 5   # ambiguous result, needs manual resolution


class Outgoingtransaction(models.Model):
    created_at = models.DateTimeField(auto_now=False, auto_now_add=True)
    signing_initiated_at = models.DateTimeField(null=True, default=None)
    broadcasted_at = models.DateTimeField(null=True, default=None)
    completed_at = models.DateTimeField(null=True, default=None)

    status = models.IntegerField(choices=OutgoingStatus.choices, default=OutgoingStatus.PENDING)

    canceled_at = models.DateTimeField(null=True, default=None)
    failed_at = models.DateTimeField(null=True, default=None)
    failed_reason = models.TextField(null=True, default=None)
    review_reason = models.TextField(null=True, default=None)

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    from_account = models.ForeignKey(Account, on_delete=models.PROTECT)

    destination = models.TextField(null=True, default=None)
    destination_type = models.IntegerField(choices=DestinationType.choices, default=DestinationType.ONCHAIN)

    # Amount in BTC or some other base unit
    amount = models.DecimalField(max_digits=65, decimal_places=16, default=5000)

    # On-chain: transaction in base64 format
    tx_generated_at = models.DateTimeField(null=True, default=None)
    transaction_base64 = models.TextField(null=True, default=None)

    # On-chain: transaction id after broadcasted
    # LN: payment hash
    txid = models.TextField(null=True, default=None)

    # LN: payment preimage (proof of payment)
    payment_preimage = models.TextField(null=True, default=None)

    # Batching: non-urgent txs can be batched into a single on-chain transaction
    is_urgent = models.BooleanField(default=True)

    # Fee tracking: what we charged the user vs what we actually paid
    fee_charged = models.DecimalField(max_digits=65, decimal_places=16, null=True, default=None)
    fee_actual = models.DecimalField(max_digits=65, decimal_places=16, null=True, default=None)

    # transaction object is created before any action
    transaction = models.ForeignKey(Transaction, null=True, default=None, on_delete=models.PROTECT)

    # reversal transaction if payment failed
    reversal_transaction = models.ForeignKey(Transaction, null=True, default=None, on_delete=models.PROTECT, related_name='reversed_outgoing')

    class Meta:
        pass

    def __str__(self):
        return f"{self.get_destination_type_display()}: {self.destination}, Amount: {self.amount}, Created: {self.created_at}, id: {self.id}"


class RecurringPayment(models.Model):
    """
    Recurring payment from an account to any destination.
    Destination can be a lightning address, on-chain address, or internal account.
    """
    class Frequency(models.TextChoices):
        ONCE = 'once'
        DAILY = 'daily'
        WEEKLY = 'weekly'
        BIWEEKLY = 'biweekly'
        MONTHLY = 'monthly'

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='recurring_payments_out')

    # Destination: LN address (user@domain) or on-chain address (bc1...)
    destination = models.CharField(max_length=255, default='')
    destination_type = models.IntegerField(choices=DestinationType.choices, default=DestinationType.ONCHAIN)

    # Amount: either BTC (amount field) or fiat (amount_fiat + amount_currency)
    # If amount_currency is set, amount_fiat is the fiat value and amount is computed at payment time
    amount = models.DecimalField(max_digits=65, decimal_places=16)
    amount_fiat = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=None)
    amount_currency = models.CharField(max_length=3, blank=True, default='')  # USD, EUR, CHF

    frequency = models.CharField(max_length=10, choices=Frequency.choices)

    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, default=None)
    next_payment = models.DateTimeField()
    end_date = models.DateTimeField(null=True, default=None)  # auto-deactivate after this date
    last_payment = models.DateTimeField(null=True, default=None)
    last_error = models.TextField(blank=True, default='')

    description = models.CharField(max_length=255, blank=True, default='')

    def compute_next_payment(self):
        """Calculate the next payment datetime based on frequency.
        Advances past now — skips missed intervals instead of catching up."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        base = self.next_payment or now

        if self.frequency == self.Frequency.DAILY:
            delta = datetime.timedelta(days=1)
        elif self.frequency == self.Frequency.WEEKLY:
            delta = datetime.timedelta(weeks=1)
        elif self.frequency == self.Frequency.BIWEEKLY:
            delta = datetime.timedelta(weeks=2)
        elif self.frequency == self.Frequency.MONTHLY:
            # Advance month by month until past now
            nxt = base
            while nxt <= now:
                month = nxt.month % 12 + 1
                year = nxt.year + (1 if month == 1 else 0)
                day = min(nxt.day, 28)
                nxt = nxt.replace(year=year, month=month, day=day)
            return nxt
        else:
            delta = datetime.timedelta(days=1)

        # Advance past now in one step
        nxt = base + delta
        if nxt <= now:
            missed = int((now - base) / delta)
            nxt = base + delta * (missed + 1)
        return nxt

    @property
    def is_fiat(self):
        return bool(self.amount_currency and self.amount_fiat)

    def __str__(self):
        if self.is_fiat:
            return f"{self.amount_fiat} {self.amount_currency} {self.frequency} → {self.destination}"
        amt_sats = int(self.amount * 100_000_000)
        return f"{amt_sats} sats {self.frequency} → {self.destination}"


class RecurringPaymentExecution(models.Model):
    """Log of each recurring payment execution attempt."""
    class Status(models.TextChoices):
        SUCCESS = 'success'
        FAILED = 'failed'

    created_at = models.DateTimeField(auto_now_add=True)
    recurring_payment = models.ForeignKey(RecurringPayment, on_delete=models.CASCADE, related_name='executions')
    status = models.CharField(max_length=10, choices=Status.choices)
    amount = models.DecimalField(max_digits=65, decimal_places=16)
    amount_fiat = models.DecimalField(max_digits=20, decimal_places=2, null=True, default=None)
    amount_currency = models.CharField(max_length=3, blank=True, default='')
    transaction = models.ForeignKey(Transaction, null=True, default=None, on_delete=models.PROTECT)
    error = models.TextField(blank=True, default='')

    def __str__(self):
        return f"RP#{self.recurring_payment_id} {self.status} {int(self.amount * 100_000_000)} sats @ {self.created_at}"










