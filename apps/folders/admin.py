from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.folders.models import Folder


class FolderAdmin(SimpleHistoryAdmin):
    list_display = ("id", "app", "name", "selected", "active")


admin.site.register(Folder, FolderAdmin)
