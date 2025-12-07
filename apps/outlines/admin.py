from django.contrib import admin

from .models import Outline, OutlineItem


class OutlineItemInline(admin.TabularInline):
    model = OutlineItem
    extra = 0
    fields = ["content", "parent", "order", "collapsed"]


@admin.register(Outline)
class OutlineAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "matter", "created_at", "updated_at"]
    list_filter = ["user", "matter"]
    search_fields = ["title"]
    inlines = [OutlineItemInline]


@admin.register(OutlineItem)
class OutlineItemAdmin(admin.ModelAdmin):
    list_display = ["__str__", "outline", "parent", "order", "collapsed"]
    list_filter = ["outline"]
    search_fields = ["content"]
