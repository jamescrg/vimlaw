from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import CustomUser
from apps.folders.models import Folder
from apps.intakes.models import Intake
from utils.models import AuditMixin


class Contact(AuditMixin, models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, blank=True, null=True)
    name = models.CharField(max_length=100)
    company = models.CharField(max_length=100, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    phone1 = models.CharField(max_length=50, blank=True, null=True)
    phone1_label = models.CharField(max_length=10, blank=True, null=True)
    phone2 = models.CharField(max_length=50, blank=True, null=True)
    phone2_label = models.CharField(max_length=10, blank=True, null=True)
    phone3 = models.CharField(max_length=50, blank=True, null=True)
    phone3_label = models.CharField(max_length=10, blank=True, null=True)
    email = models.EmailField(max_length=100, blank=True, null=True)
    email2 = models.EmailField(max_length=100, blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True)
    map = models.CharField(max_length=255, blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True, null=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    intake = models.ForeignKey(Intake, on_delete=models.SET_NULL, null=True)
    client_status = models.CharField(max_length=100, default="Nonclient")
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_contact"
        indexes = [
            models.Index(fields=["client_status"]),
            models.Index(fields=["user"]),
            models.Index(fields=["folder"]),
        ]
