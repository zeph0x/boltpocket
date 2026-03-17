from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.utils.html import format_html
from .models import SystemUser, Wallet, TxComment, BoltCard, BoltCardHit
from accounts.models import Asset, Account


admin.site.register(SystemUser)
admin.site.register(TxComment)


class WalletAdmin(admin.ModelAdmin):
    list_display = ('id', 'creator', 'ln_address_display', 'is_active', 'created_at')
    readonly_fields = ('access_key_hash', 'account', 'public_id', 'created_at', 'updated_at')

    def ln_address_display(self, obj):
        return obj.ln_address()
    ln_address_display.short_description = 'Lightning Address'

    def get_fields(self, request, obj=None):
        if obj is None:
            return ('creator', 'is_active')
        return ('creator', 'account', 'public_id', 'is_active', 'created_at', 'updated_at')


admin.site.register(Wallet, WalletAdmin)


class BoltCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'wallet', 'is_enabled', 'counter', 'tx_limit', 'daily_limit')
    readonly_fields = ('external_id', 'card_secret_hash', 'counter', 'daily_spent', 'daily_spent_date', 'created_at', 'updated_at')
    list_filter = ('is_enabled',)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ('wallet', 'uid', 'tx_limit', 'daily_limit', 'is_enabled')
        return (
            'wallet', 'uid', 'external_id', 'card_secret_hash',
            'counter', 'tx_limit', 'daily_limit', 'daily_spent', 'daily_spent_date',
            'is_enabled', 'otp', 'created_at', 'updated_at',
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('wizard/', self.admin_site.admin_view(self.wizard_view), name='wallets_boltcard_wizard'),
        ]
        return custom + urls

    def wizard_view(self, request):
        """Create Wallet + BoltCard in one step."""
        context = {**self.admin_site.each_context(request), 'title': 'Create BoltCard Wallet'}

        if request.method == 'POST':
            uid = request.POST.get('uid', '').replace(':', '').replace(' ', '').replace('-', '').upper()
            tx_limit = int(request.POST.get('tx_limit', 0) or 0)
            daily_limit = int(request.POST.get('daily_limit', 0) or 0)

            errors = []
            if not uid:
                errors.append('Card UID is required')
            elif len(uid) != 14:
                errors.append(f'Card UID must be 7 bytes (14 hex chars), got {len(uid)}')
            else:
                try:
                    bytes.fromhex(uid)
                except ValueError:
                    errors.append('Card UID must be valid hex')

            if errors:
                context.update({'errors': errors, 'uid': uid, 'tx_limit': tx_limit, 'daily_limit': daily_limit})
                return render(request, 'wallets/admin_create_boltcard_wallet.html', context)

            # Create wallet
            btc_asset = Asset.objects.filter(ticker='BTC').first()
            if not btc_asset:
                btc_asset = Asset.objects.create(
                    ticker='BTC', atomic_unit='sat', base_unit='btc', description='Bitcoin',
                )
            account = Account.objects.create(asset=btc_asset)
            raw_key, client_hash, server_hash = Wallet.generate_access_key()
            wallet = Wallet.objects.create(
                creator=request.user,
                account=account,
                access_key_hash=server_hash,
            )

            # Create bolt card
            card, card_secret, k0, k1, k2 = BoltCard.create_card(
                wallet=wallet,
                uid=uid,
                tx_limit=tx_limit,
                daily_limit=daily_limit,
            )

            # Generate QR
            import qrcode
            import qrcode.image.svg
            import io

            auth_url = request.build_absolute_uri(f'/boltcard/auth/?a={card.otp}&s={card_secret}')
            img = qrcode.make(auth_url, image_factory=qrcode.image.svg.SvgPathImage)
            buf = io.BytesIO()
            img.save(buf)
            qr_svg = buf.getvalue().decode()

            wallet_url = request.build_absolute_uri(f'/wallet/#{raw_key}')

            from django.conf import settings
            domain = getattr(settings, 'LNURL_DOMAIN', 'localhost')

            context['result'] = {
                'wallet_id': wallet.id,
                'uid': uid,
                'wallet_url': wallet_url,
                'ln_address': wallet.ln_address(domain),
                'auth_url': auth_url,
                'card_secret': card_secret,
                'k0': k0, 'k1': k1, 'k2': k2,
                'qr_svg': qr_svg,
            }

        return render(request, 'wallets/admin_create_boltcard_wallet.html', context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['wizard_url'] = 'wallets_boltcard_wizard'
        return super().changelist_view(request, extra_context=extra_context)


admin.site.register(BoltCard, BoltCardAdmin)


class BoltCardHitAdmin(admin.ModelAdmin):
    list_display = ('id', 'card', 'amount_sats', 'was_paid', 'old_counter', 'new_counter', 'created_at')
    list_filter = ('was_paid',)
    readonly_fields = ('card', 'ip', 'user_agent', 'old_counter', 'new_counter', 'amount_sats', 'was_paid', 'created_at')


admin.site.register(BoltCardHit, BoltCardHitAdmin)
