# Register your models here.

from django.contrib import admin

from apps.case.models import Document, Highlight, Label, Note

admin.site.register(Document)
admin.site.register(Highlight)
admin.site.register(Label)
admin.site.register(Note)
