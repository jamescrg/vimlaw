from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.folders.models import Folder
from apps.matters.models import Matter
from utils.models import AuditMixin


class Task(AuditMixin, models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    date_due = models.DateField(blank=True, null=True)
    date_completed = models.DateField(blank=True, null=True)
    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    priority = models.IntegerField(default=5)
    custom_order = models.DecimalField(
        max_digits=18, decimal_places=8, null=True, blank=True, default=None
    )
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        # Auto-set date_completed when status changes to Complete
        if self.pk:
            try:
                old_task = Task.objects.get(pk=self.pk)
                old_status = old_task.status
            except Task.DoesNotExist:
                old_status = None
        else:
            old_status = None

        # Set date_completed when status becomes Complete
        if self.status == "Complete" and old_status != "Complete":
            self.date_completed = timezone.now().date()
        # Clear date_completed when status changes from Complete to something else
        elif self.status != "Complete" and old_status == "Complete":
            self.date_completed = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} : {self.id}"

    class Meta:
        db_table = "app_task"

    @property
    def matter_display_name(self):
        if self.matter:
            full_name = self.matter.name
            short_name = self.matter.name[0:15]
            display_name = short_name
            if len(full_name) > len(short_name):
                display_name = short_name + " ..."
            return display_name
        else:
            return "Admin"


class TaskNote(AuditMixin, models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="notes")
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(null=True)
    details = models.TextField(null=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "app_task_note"
        ordering = ["-date", "-time"]

    def __str__(self):
        return f"Note for {self.task.description} on {self.date}"


class UserTaskNoteView(models.Model):
    """Tracks when users last viewed task notes for badge notification system."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_user_task_note_view"
        unique_together = ("user", "task")
        indexes = [
            models.Index(fields=["user", "task"]),
        ]

    def __str__(self):
        return f"{self.user.username} viewed {self.task.description} notes at {self.last_viewed_at}"
