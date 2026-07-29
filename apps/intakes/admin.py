from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import FormSubmission, FormTemplate, InboundEmail, Intake


class IntakeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "name",
        "date",
        "phone",
        "email",
    )


class FormTemplateAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name", "version", "is_active", "updated_at")
    list_filter = ("is_active",)


class FormSubmissionAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "template_name",
        "intake",
        "status",
        "recipient_email",
        "submitted_at",
    )
    list_filter = ("status",)
    # The snapshot and answers are the record of what was asked and answered;
    # editing them by hand would falsify it.
    readonly_fields = ("uuid", "schema_snapshot", "answers")


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
admin.site.register(FormTemplate, FormTemplateAdmin)
admin.site.register(FormSubmission, FormSubmissionAdmin)
admin.site.register(InboundEmail, InboundEmailAdmin)
