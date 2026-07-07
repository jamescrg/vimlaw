from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin


class Event(AuditMixin, models.Model):
    EVENT_TYPE_CHOICES = [
        ("Zoom", "Zoom"),
        ("Virtual", "Virtual"),
        ("Phone", "Phone"),
        ("In-person", "In-person"),
    ]

    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True
    )
    assigned_to = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_events",
    )
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField(null=True)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    party = models.CharField(max_length=50, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    event_type = models.CharField(
        max_length=50, choices=EVENT_TYPE_CHOICES, blank=True, null=True
    )
    # CharField (not TextField) on purpose: location is a short pointer — a
    # meeting link or "courthouse & courtroom" — not a notes field. 150 still
    # fits a Zoom URL + passcode.
    location = models.CharField(max_length=150, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    # When this event was last successfully pushed to Google Calendar. NULL means
    # never pushed. The push is needed whenever this is NULL or older than
    # updated_at (a local edit since the last sync) — that single comparison
    # drives create, update, first-connect backfill, and retry-after-failure.
    google_synced_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords(table_name="agenda_historicalevent")

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


class PendingGoogleDeletion(models.Model):
    """A Google Calendar event that must be deleted remotely after a local
    delete whose push failed. The Event row is gone, so the marker can't live on
    it; reconcile() drains this and removes the record once Google confirms."""

    google_id = models.CharField(max_length=255, unique=True)
    calendar_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Pending deletion of {self.google_id}"

    class Meta:
        db_table = "app_calendar_pending_deletion"
