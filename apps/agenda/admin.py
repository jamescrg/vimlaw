from django.contrib import admin

from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task


class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "description",
        "status",
        "matter",
    )


class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "matter", "description")


admin.site.register(Task, TaskAdmin)
admin.site.register(Event, EventAdmin)
