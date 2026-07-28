from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import InboundEmail, Intake


class IntakeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "name",
        "date",
        "phone",
        "email",
    )


class InboundEmailAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "received_at",
        "sender",
        "subject",
        "status",
        "intake",
    )


admin.site.register(Intake, IntakeAdmin)
admin.site.register(InboundEmail, InboundEmailAdmin)
