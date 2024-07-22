from django.contrib import admin

from apps.invoicing.models import Invoice


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


admin.site.register(Invoice, InvoiceAdmin)
