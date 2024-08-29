from django.contrib import admin

from apps.billing.invoices.models import Invoice
from apps.billing.payments.models import Payment


class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "matter",
        "created_at",
        "comment",
        "show_comp",
        "status",
        "created_by",
    ]
    list_filter = ["created_by", "matter"]
    search_fields = ["matter__name", "comment", "created_by__username", "status"]
    ordering = ["-created_at"]


class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "matter",
        "date",
        "payment_method",
        "detail",
        "amount",
    ]
    list_filter = ["payment_method", "matter"]
    search_fields = ["matter__name", "detail"]


admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Payment, PaymentAdmin)
