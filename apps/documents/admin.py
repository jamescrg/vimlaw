# Register your models here.

from django.contrib import admin

from apps.documents.models import Document, Label

admin.site.register(Document)
admin.site.register(Label)
