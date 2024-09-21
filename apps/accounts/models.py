from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.managers import CustomUserManager


class CustomUser(AbstractUser):
    google_contacts_credentials = models.TextField(null=True, blank=True)
    google_calendar_credentials = models.TextField(null=True, blank=True)
    user_rate = models.IntegerField(default=0)
    initials = models.CharField(max_length=100, null=True, blank=True)

    objects = CustomUserManager()
