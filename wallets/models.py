import os
import base64
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from accounts.models import Account, Transaction


def generate_public_id():
    """Generate a random 16-byte public ID, returned as hex string."""
    return os.urandom(16).hex()


def public_id_to_base32(hex_id):
    """Encode a hex public ID as lowercase base32 without padding."""
    return base64.b32encode(bytes.fromhex(hex_id)).decode().lower().rstrip('=')


class AccountManager(BaseUserManager):

    def create_user(self, email, username, password=None):
        if not email:
            raise ValueError("You need an email address")
        if not username:
            raise ValueError("You need an username")
        user = self.model(
            email=email,
            username=username,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None):
        user = self.create_user(
            email=email,
            username=username,
            password=password,
        )
        user.is_admin = True
        user.is_superuser = True
        user.is_staff = True
        user.set_password(password)
        user.save(using=self._db)
        return user


class SystemUser(AbstractBaseUser):
    """
    An individual signing in to the system.
    """
    created_at = models.DateTimeField(verbose_name="created at", auto_now_add=True)
    last_login = models.DateTimeField(verbose_name="last login", auto_now=True)

    email = models.EmailField(max_length=60, verbose_name='email address', unique=True)
    username = models.CharField(max_length=30, unique=True)

    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.username

    def has_perm(self, perm, obj=None):
        return self.is_admin

    def has_module_perms(self, app_label):
        return True


class Wallet(models.Model):
    """
    A wallet linked to a BTC account.
    Accessed via a secret key (hashed in DB).
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    creator = models.ForeignKey(SystemUser, on_delete=models.PROTECT, related_name='wallets')
    account = models.OneToOneField(Account, on_delete=models.PROTECT)

    # Random public identifier — used for lightning address
    public_id = models.CharField(max_length=32, unique=True, default=generate_public_id, editable=False)

    # SHA-256(SHA-256(raw_key)) — double hashed, client sends first hash
    access_key_hash = models.CharField(max_length=64, unique=True)

    is_active = models.BooleanField(default=True)

    # Settings
    DISPLAY_CURRENCY_CHOICES = [
        ('BTC', 'BTC'),
        ('sats', 'sats'),
        ('USD', 'USD'),
        ('EUR', 'EUR'),
        ('CHF', 'CHF'),
    ]
    FIAT_CURRENCY_CHOICES = [
        ('USD', 'USD'),
        ('EUR', 'EUR'),
        ('CHF', 'CHF'),
    ]
    primary_currency = models.CharField(max_length=4, choices=DISPLAY_CURRENCY_CHOICES, default='CHF')
    secondary_currency = models.CharField(max_length=4, choices=DISPLAY_CURRENCY_CHOICES, default='BTC')

    def set_access_key_from_client_hash(self, client_hash):
        """Store SHA-256(client_hash) where client_hash = SHA-256(raw_key)"""
        import hashlib
        self.access_key_hash = hashlib.sha256(client_hash.encode()).hexdigest()

    def verify_client_hash(self, client_hash):
        """Verify SHA-256(client_hash) matches stored hash"""
        import hashlib
        return self.access_key_hash == hashlib.sha256(client_hash.encode()).hexdigest()

    @staticmethod
    def generate_access_key():
        """Generate a random access key. Returns (raw_key, client_hash, server_hash)"""
        import secrets, hashlib
        raw_key = secrets.token_hex(16)
        client_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        server_hash = hashlib.sha256(client_hash.encode()).hexdigest()
        return raw_key, client_hash, server_hash

    @property
    def ln_address_local(self):
        """The local part of the lightning address (base32-encoded random ID)."""
        return public_id_to_base32(self.public_id)

    def ln_address(self, domain=None):
        """Full lightning address: <base32>@<domain>."""
        from django.conf import settings
        domain = domain or getattr(settings, 'LNURL_DOMAIN', 'localhost')
        return f'{self.ln_address_local}@{domain}'

    def __str__(self):
        return f"Wallet {self.id} ({self.creator})"

    class Meta:
        pass



class BoltCard(models.Model):
    """
    An NXP NTAG424 DNA bolt card linked to a wallet.
    One wallet can have multiple bolt cards.

    Keys (K0/K1/K2) are stored encrypted. The encryption key is derived
    from a card_secret that lives only in the NFC card's URL — never in the DB.
    DB breach = useless without the physical card.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='boltcards')

    # NFC card UID — 7 bytes hex (14 chars)
    # Not unique — some card batches have duplicate UIDs
    uid = models.CharField(max_length=14, db_index=True)

    # SHA-256(card_secret) — for verifying the secret without storing it
    card_secret_hash = models.CharField(max_length=64, default='')

    # Encrypted card keys — AES-GCM encrypted with key derived from card_secret
    # Stored as hex: nonce (16) + ciphertext (16) + tag (16)
    k0_enc = models.TextField(default='')
    k1_enc = models.TextField(default='')
    k2_enc = models.TextField(default='')

    # Encrypted previous keys — for key rotation / card reset
    prev_k0_enc = models.TextField(default='')
    prev_k1_enc = models.TextField(default='')
    prev_k2_enc = models.TextField(default='')

    # Anti-replay counter — must strictly increase with each tap
    counter = models.IntegerField(default=0)

    # Spending limits
    tx_limit = models.IntegerField(default=0, help_text='Max sats per transaction, 0 = no limit')
    daily_limit = models.IntegerField(default=0, help_text='Max sats per day, 0 = no limit')
    daily_spent = models.IntegerField(default=0)
    daily_spent_date = models.DateField(null=True, default=None)

    # External ID for LNURL endpoint (random, not card UID)
    external_id = models.CharField(max_length=64, unique=True, db_index=True)

    is_enabled = models.BooleanField(default=True)

    # One-time password for card provisioning
    otp = models.CharField(max_length=32, blank=True, default='')

    # --- Crypto helpers ---

    @staticmethod
    def _derive_enc_key(card_secret):
        """Derive a 32-byte AES key from the card_secret."""
        import hashlib
        return hashlib.sha256(card_secret.encode()).digest()

    @staticmethod
    def _encrypt(plaintext_hex, card_secret):
        """Encrypt a hex key string. Returns hex(nonce + ciphertext + tag)."""
        from Crypto.Cipher import AES as _AES
        key = BoltCard._derive_enc_key(card_secret)
        cipher = _AES.new(key, _AES.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(bytes.fromhex(plaintext_hex))
        return (cipher.nonce + ciphertext + tag).hex()

    @staticmethod
    def _decrypt(enc_hex, card_secret):
        """Decrypt a hex blob. Returns the plaintext hex key string."""
        from Crypto.Cipher import AES as _AES
        key = BoltCard._derive_enc_key(card_secret)
        raw = bytes.fromhex(enc_hex)
        nonce = raw[:16]
        tag = raw[-16:]
        ciphertext = raw[16:-16]
        cipher = _AES.new(key, _AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.hex()

    def decrypt_keys(self, card_secret):
        """Decrypt and return (k0, k1, k2) using the card_secret."""
        return (
            self._decrypt(self.k0_enc, card_secret),
            self._decrypt(self.k1_enc, card_secret),
            self._decrypt(self.k2_enc, card_secret),
        )

    def verify_card_secret(self, card_secret):
        """Verify the card_secret matches the stored hash."""
        import hashlib
        return self.card_secret_hash == hashlib.sha256(card_secret.encode()).hexdigest()

    @staticmethod
    def generate_keys():
        """Generate random K0, K1, K2 keys."""
        import secrets
        return secrets.token_hex(16), secrets.token_hex(16), secrets.token_hex(16)

    @staticmethod
    def generate_card_secret():
        """Generate a random card_secret (32 hex chars)."""
        import secrets
        return secrets.token_hex(16)

    @staticmethod
    def generate_external_id():
        """Generate a random external ID for the LNURL endpoint."""
        import secrets
        return secrets.token_hex(16)

    @staticmethod
    def create_card(wallet, uid, tx_limit=0, daily_limit=0):
        """
        Create a new bolt card with encrypted keys.
        Returns (card, card_secret, k0, k1, k2).
        card_secret and plaintext keys must be shown once and not stored.
        """
        import secrets
        import hashlib

        k0, k1, k2 = BoltCard.generate_keys()
        card_secret = BoltCard.generate_card_secret()
        card_secret_hash = hashlib.sha256(card_secret.encode()).hexdigest()

        card = BoltCard.objects.create(
            wallet=wallet,

            uid=uid,
            card_secret_hash=card_secret_hash,
            k0_enc=BoltCard._encrypt(k0, card_secret),
            k1_enc=BoltCard._encrypt(k1, card_secret),
            k2_enc=BoltCard._encrypt(k2, card_secret),
            external_id=BoltCard.generate_external_id(),
            otp=secrets.token_hex(16),
            tx_limit=tx_limit,
            daily_limit=daily_limit,
        )

        return card, card_secret, k0, k1, k2

    def authenticate_tap(self, card_secret, p, c, ip=None, user_agent=''):
        """
        Full card tap verification: secret check, key decryption, NXP424
        SUN/CMAC verification, first-tap UID storage, atomic counter update,
        and BoltCardHit logging.

        Returns (hit, error_string).
        On success: hit is a BoltCardHit instance, error is None.
        On failure: hit is None, error is a string.
        """
        import logging
        from .nxp424 import verify_tap
        logger = logging.getLogger(__name__)

        if not self.verify_card_secret(card_secret):
            return None, 'Invalid card secret'

        try:
            k0, k1, k2 = self.decrypt_keys(card_secret)
        except Exception:
            return None, 'Key decryption failed'

        success, counter_int, error, actual_uid = verify_tap(
            p_hex=p.upper(),
            c_hex=c.upper(),
            k1_hex=k1,
            k2_hex=k2,
            expected_uid_hex=self.uid,
        )

        if not success:
            return None, f'Card verification failed: {error}'

        # First tap: store the real UID (replaces placeholder)
        if self.uid == '00000000000000' and actual_uid:
            BoltCard.objects.filter(id=self.id).update(uid=actual_uid)
            logger.info(f'BoltCard {self.id} first tap — UID set to {actual_uid}')

        # Anti-replay: atomic check-and-update
        old_counter = self.counter
        rows = BoltCard.objects.filter(id=self.id, counter__lt=counter_int).update(counter=counter_int)
        if rows == 0:
            return None, 'Replay detected — tap card again'

        # Log the tap
        hit = BoltCardHit.objects.create(
            card=self,
            ip=ip,
            user_agent=user_agent,
            old_counter=old_counter,
            new_counter=counter_int,
        )

        return hit, None

    def reset_daily_spent(self):
        """Reset daily spent counter if it's a new day."""
        import datetime
        today = datetime.date.today()
        if self.daily_spent_date != today:
            self.daily_spent = 0
            self.daily_spent_date = today
            self.save(update_fields=['daily_spent', 'daily_spent_date'])

    def check_limits(self, amount_sats):
        """Check if a transaction is within limits. Returns (ok, reason)."""
        self.reset_daily_spent()
        if self.tx_limit > 0 and amount_sats > self.tx_limit:
            return False, f'Exceeds per-transaction limit ({self.tx_limit} sats)'
        if self.daily_limit > 0 and self.daily_spent + amount_sats > self.daily_limit:
            return False, f'Exceeds daily limit ({self.daily_limit} sats)'
        return True, ''

    def record_spend(self, amount_sats):
        """Record a spend against daily limit."""
        self.reset_daily_spent()
        self.daily_spent += amount_sats
        self.save(update_fields=['daily_spent'])

    def __str__(self):
        return f"BoltCard {self.uid} → Wallet {self.wallet_id}"

    class Meta:
        pass


class BoltCardHit(models.Model):
    """
    Log of every bolt card tap / LNURL-withdraw attempt.
    """
    created_at = models.DateTimeField(auto_now_add=True)

    card = models.ForeignKey(BoltCard, on_delete=models.PROTECT, related_name='hits')

    ip = models.GenericIPAddressField(null=True, default=None)
    user_agent = models.TextField(blank=True, default='')

    old_counter = models.IntegerField()
    new_counter = models.IntegerField()

    # Amount paid (0 if not yet paid or rejected)
    amount_sats = models.IntegerField(default=0)
    was_paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Hit {self.id} on {self.card} — {self.amount_sats} sats"

    class Meta:
        pass


class SiteSettings(models.Model):
    """Singleton site-wide settings editable from admin."""
    info_banner = models.TextField(
        blank=True, default='This is a demo instance meant for educational and testing purposes only.',
        help_text='Text displayed on the wallet info page. Leave empty to hide.',
    )

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return 'Site Settings'

    def save(self, *args, **kwargs):
        # Enforce singleton
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TxComment(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    comment = models.CharField(max_length=1500)
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.created_at}: {self.comment}"
