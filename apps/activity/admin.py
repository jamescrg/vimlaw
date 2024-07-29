from django.contrib import admin

from .models import ExpenseEntry, TimeEntry


class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "user", "matter", "actions", "rate", "fee")


class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "user", "matter", "description", "amount")


admin.site.register(TimeEntry, TimeEntryAdmin)
admin.site.register(ExpenseEntry, ExpenseAdmin)
