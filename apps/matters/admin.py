from django.contrib import admin

from .models import Matter, Rate


class MatterAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


class RateAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "matter", "matter_rate")


admin.site.register(Matter, MatterAdmin)
admin.site.register(Rate, RateAdmin)
