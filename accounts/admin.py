from django.contrib import admin
from .models import Account, Asset, Transaction, DepositEndpoint, IncomingTransaction, Outgoingtransaction, RecurringPayment


admin.site.disable_action('delete_selected')


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AssetAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'description', 'outgoing_tx_fee_amount', 'ln_fee_floor', 'ln_fee_percentage')
    readonly_fields = ('id', 'ticker', 'atomic_unit', 'base_unit', 'description', 'blockchain_fee_account', 'custody_billing_account', 'blockheight', 'scan_started_at')
    fields = ('ticker', 'description', 'atomic_unit', 'base_unit', 'outgoing_tx_fee_amount', 'ln_fee_floor', 'ln_fee_percentage', 'blockchain_fee_account', 'custody_billing_account', 'blockheight', 'scan_started_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AccountAdmin(ReadOnlyAdmin):
    list_display = ('id', 'account_type', 'balance', 'allow_negative', 'asset')
    list_filter = ('account_type', 'allow_negative')


admin.site.register(Asset, AssetAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(Transaction, ReadOnlyAdmin)
admin.site.register(DepositEndpoint, ReadOnlyAdmin)
admin.site.register(IncomingTransaction, ReadOnlyAdmin)
admin.site.register(Outgoingtransaction, ReadOnlyAdmin)
admin.site.register(RecurringPayment, ReadOnlyAdmin)
