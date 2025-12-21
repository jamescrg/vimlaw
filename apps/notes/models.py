from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.matters.models import Matter
from utils.models import AuditMixin

User = get_user_model()


class Note(AuditMixin, models.Model):
    """Rich markdown note for a matter with inline document/highlight references."""

    CATEGORY_CHOICES = [
        ("analysis", "Analysis"),
        ("drafting", "Drafting"),
        ("interview", "Interview"),
        ("issue", "Issue"),
        ("note", "Note"),
        ("research", "Research"),
    ]

    author = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_notes",
    )
    matter = models.ForeignKey(
        Matter, on_delete=models.CASCADE, related_name="notes", null=True, blank=True
    )
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="note")
    topic = models.CharField(max_length=255, blank=True, null=True)
    content = models.TextField(blank=True, default="")  # Markdown content

    # Source references (tracked separately from inline [[doc:id]] syntax)
    documents = models.ManyToManyField(
        "case.Document", blank=True, related_name="notes"
    )
    highlights = models.ManyToManyField(
        "case.Highlight", blank=True, related_name="notes"
    )

    importance = models.PositiveIntegerField(default=5)
    labels = models.ManyToManyField("case.Label", related_name="notes", blank=True)

    viewed_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.title

    class Meta:
        db_table = "app_note"
        ordering = ["-updated_at"]


class NoteView(models.Model):
    """Tracks when each user last viewed each note."""

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="note_views",
    )
    note = models.ForeignKey(
        Note,
        on_delete=models.CASCADE,
        related_name="views",
    )
    created_at = models.DateTimeField(default=timezone.now)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_note_view"
        unique_together = ("user", "note")
        ordering = ["-viewed_at"]

    def __str__(self):
        return f"{self.user} viewed {self.note} at {self.viewed_at}"
