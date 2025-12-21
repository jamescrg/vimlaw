from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.matters.models import Matter, Role
from apps.matters.rates.models import Rate


class MatterAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name")


class RateAdmin(SimpleHistoryAdmin):
    list_display = ("id", "user", "matter", "matter_rate")


class RoleAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name")


admin.site.register(Matter, MatterAdmin)
admin.site.register(Rate, RateAdmin)
admin.site.register(Role, RoleAdmin)
