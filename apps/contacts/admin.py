from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Contact


class ContactAdmin(SimpleHistoryAdmin):
    list_display = ("id", "user", "folder", "name", "phone1", "email", "google_id")


admin.site.register(Contact, ContactAdmin)
