from django.contrib import admin
from .models import Account, Asset, Transaction, DepositEndpoint, IncomingTransaction, Outgoingtransaction, RecurringPayment


admin.site.disable_action('delete_selected')


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    list_display_links = None


admin.site.register(Account, ReadOnlyAdmin)
admin.site.register(Asset, ReadOnlyAdmin)
admin.site.register(Transaction)
admin.site.register(DepositEndpoint)
admin.site.register(IncomingTransaction)
admin.site.register(Outgoingtransaction)
admin.site.register(RecurringPayment)
