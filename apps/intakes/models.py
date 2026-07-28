from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from utils.models import AuditMixin


class Intake(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100)
    date = models.DateField(null=True)
    importance = models.PositiveIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    address = models.CharField(max_length=255, blank=True, null=True)
    disputed_property = models.CharField(max_length=255, blank=True, null=True)
    value = models.IntegerField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(max_length=100, blank=True, null=True)
    practice_area = models.ForeignKey(
        "matters.PracticeArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intakes",
    )
    source = models.CharField(max_length=50, null=True)
    status = models.CharField(max_length=50, default="Open")
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name} : {self.id}"

    def save(self, *args, **kwargs):
        # If this is an existing intake (not new) and status changed from Open to something else
        if self.pk:
            try:
                old_intake = Intake.objects.get(pk=self.pk)
                # If status changed from Open to anything else, delete view records
                if old_intake.status == "Open" and self.status != "Open":
                    # Import here to avoid circular import
                    UserIntakeView.objects.filter(intake=self).delete()
            except Intake.DoesNotExist:
                pass

        super().save(*args, **kwargs)

    class Meta:
        db_table = "app_intake"


class Note(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    intake = models.ForeignKey(Intake, on_delete=models.SET_NULL, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.type} : {self.id}"

    class Meta:
        db_table = "app_intake_note"


class InboundEmail(models.Model):
    """A message received on the Mailgun intake route. Rows are kept even
    when AI extraction fails so no forwarded message is ever lost and a
    failed row can be reprocessed."""

    id = models.BigAutoField(primary_key=True)
    message_id = models.CharField(max_length=255, unique=True)
    sender = models.CharField(max_length=255)
    recipient = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    body_plain = models.TextField(blank=True)
    stripped_text = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    # received -> processed (AI extraction succeeded) or failed (fallback
    # intake created from the raw message; error records why)
    status = models.CharField(max_length=20, default="received")
    error = models.TextField(blank=True)
    intake = models.ForeignKey(
        Intake,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails",
    )

    def __str__(self):
        return f"{self.sender} : {self.subject[:40]}"

    class Meta:
        db_table = "app_inbound_email"


class UserIntakeView(models.Model):
    """Tracks when users last viewed intake details for badge notification system."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    intake = models.ForeignKey(Intake, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    last_viewed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.user.username} viewed {self.intake.name} at {self.last_viewed_at}"
        )

    class Meta:
        db_table = "app_user_intake_view"
        unique_together = ("user", "intake")
        indexes = [
            models.Index(fields=["user", "intake"]),
        ]
