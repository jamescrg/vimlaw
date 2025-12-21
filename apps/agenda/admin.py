from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task


class TaskAdmin(SimpleHistoryAdmin):
    list_display = (
        "id",
        "user",
        "description",
        "status",
        "matter",
    )


class EventAdmin(SimpleHistoryAdmin):
    list_display = ("id", "date", "matter", "description")


admin.site.register(Task, TaskAdmin)
admin.site.register(Event, EventAdmin)
