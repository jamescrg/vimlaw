from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.trust.models import Transaction


class TransactionAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "contact",
        "date",
        "type",
        "description",
        "amount",
        "entered",
        "confirmed",
    )


admin.site.register(Transaction, TransactionAdmin)
