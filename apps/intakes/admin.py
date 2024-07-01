from django.contrib import admin
from .models import Intake


class IntakeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "date",
        "phone",
        "email",
    )


admin.site.register(Intake, IntakeAdmin)
