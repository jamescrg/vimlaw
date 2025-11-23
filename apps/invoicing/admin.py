from django.contrib import admin

from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment


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


class CreditsAdmin(admin.ModelAdmin):
    list_display = ["id", "matter", "date", "detail", "amount"]
    list_filter = ["matter"]
    search_fields = ["matter__name", "detail"]


class PaymentApplicationAdmin(admin.ModelAdmin):
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


class CreditApplicationAdmin(admin.ModelAdmin):
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
