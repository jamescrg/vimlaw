from django.contrib import admin
from .models import Task


class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "description",
        "status",
        "priority",
        "matter",
    )


admin.site.register(Task, TaskAdmin)
