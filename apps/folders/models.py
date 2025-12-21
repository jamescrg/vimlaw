from django.db import models
from simple_history.models import HistoricalRecords

from utils.models import AuditMixin

CLIENT_FOLDERS = [
    {"id": "current", "name": "Current"},
    {"id": "former", "name": "Former"},
]


class Folder(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=50, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)
    selected = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_folder"
