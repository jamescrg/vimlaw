from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment


class InvoiceAdmin(SimpleHistoryAdmin):
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
    readonly_fields = ["status"]


class PaymentAdmin(SimpleHistoryAdmin):
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


class CreditsAdmin(SimpleHistoryAdmin):
    list_display = ["id", "matter", "date", "detail", "amount"]
    list_filter = ["matter"]
    search_fields = ["matter__name", "detail"]


class PaymentApplicationAdmin(SimpleHistoryAdmin):
    list_display = [
        "id",
        "payment",
        "invoice",
        "amount_applied",
        "created_at",
    ]
    list_filter = ["payment__matter", "invoice__matter"]
    search_fields = ["payment__id", "invoice__id"]
    ordering = ["-created_at"]
    autocomplete_fields = ["payment", "invoice"]


class CreditApplicationAdmin(SimpleHistoryAdmin):
    list_display = [
        "id",
        "credit",
        "invoice",
        "amount_applied",
        "created_at",
    ]
    list_filter = ["credit__matter", "invoice__matter"]
    search_fields = ["credit__id", "invoice__id"]
    ordering = ["-created_at"]
    autocomplete_fields = ["credit", "invoice"]


admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(Credit, CreditsAdmin)
admin.site.register(PaymentApplication, PaymentApplicationAdmin)
admin.site.register(CreditApplication, CreditApplicationAdmin)
