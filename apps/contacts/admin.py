from django.contrib import admin
from .models import Contact


class ContactAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "folder", "name", "phone1", "email", "google_id")


admin.site.register(Contact, ContactAdmin)
