# Register your models here.

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.case.models import Document, Highlight, Label


class DocumentAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name", "matter", "category")


class HighlightAdmin(SimpleHistoryAdmin):
    list_display = ("id", "slug", "document", "page_number")


class LabelAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name", "matter", "color")


admin.site.register(Document, DocumentAdmin)
admin.site.register(Highlight, HighlightAdmin)
admin.site.register(Label, LabelAdmin)
