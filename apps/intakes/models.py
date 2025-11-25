from django.db import models

from apps.accounts.models import CustomUser


class Intake(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100)
    date = models.DateField(null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    disputed_property = models.CharField(max_length=255, blank=True, null=True)
    value = models.IntegerField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(max_length=100, blank=True, null=True)
    practice_area = models.CharField(max_length=50, null=True)
    source = models.CharField(max_length=50, null=True)
    status = models.CharField(max_length=50, default="Open")

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


class Note(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True)
    intake = models.ForeignKey(Intake, on_delete=models.SET_NULL, null=True)
    date = models.DateField(null=True)
    time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    type = models.CharField(max_length=50, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return f"{self.type} : {self.id}"

    class Meta:
        db_table = "app_intake_note"


class UserIntakeView(models.Model):
    """Tracks when users last viewed intake details for badge notification system."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    intake = models.ForeignKey(Intake, on_delete=models.CASCADE)
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
