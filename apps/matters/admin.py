from django.contrib import admin

from apps.matters.models import Matter, Role
from apps.matters.rates.models import Rate


class MatterAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


class RateAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "matter", "matter_rate")


class RoleAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


admin.site.register(Matter, MatterAdmin)
admin.site.register(Rate, RateAdmin)
admin.site.register(Role, RoleAdmin)
