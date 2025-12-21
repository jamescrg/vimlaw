from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin


class Event(AuditMixin, models.Model):
    LOCATION_CHOICES = [
        ("Zoom", "Zoom"),
        ("Virtual", "Virtual"),
        ("Phone", "Phone"),
        ("In-person", "In-person"),
    ]

    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    party = models.CharField(max_length=50, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(
        max_length=50, choices=LOCATION_CHOICES, blank=True, null=True
    )
    status = models.CharField(max_length=50, blank=True, null=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_event"
        indexes = [
            models.Index(fields=["matter"]),
        ]


class CalendarSyncState(models.Model):
    """Stores Google Calendar sync token for incremental sync."""

    calendar_id = models.CharField(max_length=255, unique=True)
    sync_token = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Sync state for {self.calendar_id}"

    class Meta:
        db_table = "app_calendar_sync_state"
