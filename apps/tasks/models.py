from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.folders.models import Folder
from apps.matters.models import Matter
from utils.models import AuditMixin


class ChecklistTemplate(AuditMixin, models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords(table_name="app_checklist_template_history")

    class Meta:
        db_table = "app_checklist_template"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChecklistTemplateItem(models.Model):
    template = models.ForeignKey(
        ChecklistTemplate, on_delete=models.CASCADE, related_name="items"
    )
    description = models.CharField(max_length=200)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = "app_checklist_template_item"
        ordering = ["order", "id"]

    def __str__(self):
        return self.description


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
    history = HistoricalRecords(table_name="agenda_historicaltask")

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
    history = HistoricalRecords(table_name="agenda_historicaltasknote")

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


class UserChecklistView(models.Model):
    """Tracks when users last viewed a task's checklist."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_user_checklist_view"
        unique_together = ("user", "task")

    def __str__(self):
        return f"{self.user.username} viewed {self.task.description} checklist at {self.last_viewed_at}"


class Checklist(AuditMixin, models.Model):
    task = models.OneToOneField(
        Task, on_delete=models.CASCADE, related_name="checklist"
    )
    template = models.ForeignKey(
        ChecklistTemplate, on_delete=models.SET_NULL, null=True
    )
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "app_checklist"

    def __str__(self):
        return f"Checklist: {self.name} for {self.task}"


class ChecklistItem(models.Model):
    checklist = models.ForeignKey(
        Checklist, on_delete=models.CASCADE, related_name="items"
    )
    description = models.CharField(max_length=200)
    is_complete = models.BooleanField(default=False)
    completed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        db_table = "app_checklist_item"
        ordering = ["order", "id"]

    def __str__(self):
        return self.description


def can_complete_task(task):
    try:
        checklist = task.checklist
        return not checklist.items.filter(is_complete=False).exists()
    except Checklist.DoesNotExist:
        return True
