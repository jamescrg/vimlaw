from django.contrib import admin

from apps.trust.models import Transaction


class TransactionAdmin(admin.ModelAdmin):
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
