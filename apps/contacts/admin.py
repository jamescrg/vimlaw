from django.contrib import admin

from apps.folders.models import Folder

from .models import Contact


class ContactAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "folder", "name", "phone1", "email", "google_id")


admin.site.register(Folder)
admin.site.register(Contact, ContactAdmin)
