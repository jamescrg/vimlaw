from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .expenses.models import ExpenseEntry
from .time.models import TimeEntry


class ExpenseAdmin(SimpleHistoryAdmin):
    list_display = ("id", "date", "user", "matter", "description", "amount")


class TimeEntryAdmin(SimpleHistoryAdmin):
    list_display = ("id", "date", "user", "matter", "actions", "rate", "fee")


admin.site.register(TimeEntry, TimeEntryAdmin)
admin.site.register(ExpenseEntry, ExpenseAdmin)
