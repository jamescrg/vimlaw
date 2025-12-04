from django.contrib import admin

from apps.folders.models import Folder


class FolderAdmin(admin.ModelAdmin):
    list_display = ("id", "app", "name", "selected", "active")


admin.site.register(Folder, FolderAdmin)
