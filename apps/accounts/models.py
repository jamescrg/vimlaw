from django.contrib.auth.models import AbstractUser
from django.db import models

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

    objects = CustomUserManager()

    @property
    def full_name(self):
        return f"{self.first_name.capitalize()} {self.last_name.capitalize()}"

    @property
    def role_display(self):
        return dict(ROLE_OPTIONS)[self.role]
