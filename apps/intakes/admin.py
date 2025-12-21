from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Intake


class IntakeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "name",
        "date",
        "phone",
        "email",
    )


admin.site.register(Intake, IntakeAdmin)
