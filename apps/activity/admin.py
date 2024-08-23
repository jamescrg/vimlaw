from django.contrib import admin

from .expenses.models import ExpenseEntry
from .time.models import TimeEntry


class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "user", "matter", "description", "amount")


class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "user", "matter", "actions", "rate", "fee")


admin.site.register(TimeEntry, TimeEntryAdmin)
admin.site.register(ExpenseEntry, ExpenseAdmin)
