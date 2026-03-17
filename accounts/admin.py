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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'account_type', 'balance', 'allow_negative', 'asset')
    list_filter = ('account_type', 'allow_negative')
    readonly_fields = ('id', 'created_at', 'updated_at', 'balance', 'asset', 'account_type', 'accounting_id', 'fee_credit_account')
    fields = ('id', 'created_at', 'updated_at', 'asset', 'account_type', 'balance', 'allow_negative', 'accounting_id', 'fee_credit_account')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Asset, AssetAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(Transaction, ReadOnlyAdmin)
admin.site.register(DepositEndpoint, ReadOnlyAdmin)
admin.site.register(IncomingTransaction, ReadOnlyAdmin)
admin.site.register(Outgoingtransaction, ReadOnlyAdmin)
admin.site.register(RecurringPayment, ReadOnlyAdmin)
