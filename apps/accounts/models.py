from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.managers import CustomUserManager

ROLE_OPTIONS = (
    ("ADMIN", "Admin"),
    ("USER", "User"),
)


class CustomUser(AbstractUser):
    google_contacts_credentials = models.TextField(null=True, blank=True)
    google_calendar_credentials = models.TextField(null=True, blank=True)
    user_rate = models.IntegerField(default=0)
    initials = models.CharField(max_length=100, null=True, blank=True)
    role = models.CharField(max_length=5, choices=ROLE_OPTIONS, default="USER")
    is_attorney = models.BooleanField(default=True)
    last_dash_check = models.DateField(null=True, blank=True)
    digest_enabled = models.BooleanField(default=False)
    digest_include_weekends = models.BooleanField(default=False)
    history = HistoricalRecords()

    objects = CustomUserManager()

    @property
    def full_name(self):
        if not self.first_name or not self.last_name:
            return self.username.capitalize()

        return f"{self.first_name.capitalize()} {self.last_name.capitalize()}"

    @property
    def role_display(self):
        return dict(ROLE_OPTIONS)[self.role]


class EmailVerificationCode(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "app_accounts_email_verification_code"

    def is_expired(self):
        return (timezone.now() - self.created_at).seconds > 300  # 5 minutes
