from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.notes.models import Note


class NoteAdmin(SimpleHistoryAdmin):
    list_display = ("id", "title", "matter", "category")


admin.site.register(Note, NoteAdmin)
