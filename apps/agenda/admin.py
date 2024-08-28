from django.contrib import admin

from apps.agenda.tasks.models import Task


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
