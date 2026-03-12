from django.db import models
from simple_history.models import HistoricalRecords

from utils.models import AuditMixin

COLOR_CHOICES = [
    ("blue", "Blue"),
    ("gray", "Gray"),
    ("green", "Green"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("red", "Red"),
    ("yellow", "Yellow"),
]


class ActivityLabel(AuditMixin, models.Model):
    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default="gray")
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        db_table = "app_activity_label"
        ordering = ["name"]
